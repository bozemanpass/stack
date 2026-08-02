# Copyright © 2024 Vulcanize
# Copyright © 2025 Bozeman Pass, Inc.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http:#www.gnu.org/licenses/>.

import base64
import hashlib
import importlib.resources
import git
import json
import os
import platform
import string
import subprocess

from pathlib import Path
from python_on_whales import DockerClient

import stack.deploy.stack as stack_util

from stack import constants
from stack.log import log_debug, log_info, log_warn
from stack.util import warn_exit, get_yaml, error_exit


class StackContainer:
    name: str
    ref: str
    path: str
    wrapper: str
    wrapper_ref: str
    content_root: str

    def __init__(self, name: str = None, ref=None, path=None, wrapper=None, wrapper_ref=None, content_root=None):
        self.name = name
        self.ref = ref
        self.path = path
        self.wrapper = wrapper
        self.wrapper_ref = wrapper_ref
        self.content_root = content_root

    def __repr__(self):
        return str(self)

    def __str__(self):
        ret = {"name": self.name, "ref": self.ref, "path": self.path,
               "wrapper": self.wrapper, "wrapper-ref": self.wrapper_ref, "content-root": self.content_root}
        return json.dumps(ret)


class ContainerSpec:
    """How one container is built.

    Two locations matter, and they are not the same thing:

      - `path` (and `spec_dir`, its resolved form) is where the *recipe* lives: the directory
        holding this container.yml, or the build.sh/Dockerfile named by the stack entry.
      - `ref` plus `content_root` is what gets *built*: the source repository, narrowed to a
        subdirectory of it when `content_root` is given.

    They coincide for a repo that carries its own Dockerfile beside the code it builds, which
    is why one field served both for a long time.  They come apart whenever the recipe lives
    elsewhere -- a wrapper, or a container.yml in a separate specs repo."""

    name: str
    ref: str
    build: str
    path: str
    wrapper: str
    wrapper_ref: str
    content_root: str
    file_path: str
    spec_dir: Path
    repo_path: Path

    def __init__(self, name: str = None, ref=None, build=None, path=None, wrapper=None, wrapper_ref=None, content_root=None):
        self.name = name
        self.ref = ref
        self.build = build
        self.path = path
        self.wrapper = wrapper
        self.wrapper_ref = wrapper_ref
        self.content_root = content_root
        self.file_path = None
        self.spec_dir = None
        self.repo_path = None

    def __repr__(self):
        return str(self)

    def __str__(self):
        ret = {"name": self.name, "ref": self.ref, "build": self.build, "path": self.path,
               "wrapper": self.wrapper, "wrapper-ref": self.wrapper_ref, "content-root": self.content_root,
               "file_path": self.file_path, "spec_dir": str(self.spec_dir) if self.spec_dir else None}
        return json.dumps(ret)

    def init_from_file(self, file_path: Path):
        # Deferred import to avoid a circular dependency.
        from stack.repos.repo_util import find_repo_root

        self.file_path = Path(file_path).as_posix()
        self.spec_dir = Path(self.file_path).parent

        y = get_yaml().load(open(file_path, "r"))
        if "container" not in y:
            error_exit(f"No 'container' section in {file_path}.")
        self.name = y["container"].get("name", self.name)
        if not self.name:
            error_exit(f"Missing required property 'name' in 'container' section of {file_path}.")
        self.ref = y["container"].get("ref")
        self.build = y["container"].get("build")
        self.wrapper = y["container"].get("wrapper", self.wrapper)
        self.wrapper_ref = y["container"].get("wrapper-ref", self.wrapper_ref)
        self.content_root = y["container"].get("content-root", self.content_root)
        self.repo_path = find_repo_root(self.spec_dir)
        return self

    def get_repo_ref(self):
        repo_url = self.get_repo_url()
        if not repo_url:
            return None

        if repo_url.startswith("https://") or repo_url.startswith("http://"):
            repo_url = repo_url.split("://", 2)[1]
            repo_host, repo_name = repo_url.split("/", 1)
        elif repo_url.startswith("git@"):
            repo_host, repo_name = repo_url.split(":", 1)
            repo_host = repo_host[4:]
        else:
            # Some other URL form (e.g. a local path) from which no ref can be derived.
            return None

        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        return f"{repo_host}/{repo_name}"

    def get_repo_name(self):
        ref = self.get_repo_ref()
        if ref:
            return ref.split("/", 1)[-1]
        return None

    def get_repo_url(self):
        if self.repo_path:
            repo = git.Repo(self.repo_path)
            return repo.remotes[0].url
        return None


def default_content_root(stack_container, spec_ref=None):
    """The content root for a stack.yml container entry that doesn't give one.

    `path` locates the container's build info within the repo at `ref`.  When no container.yml
    redirects the build at a different source repo, the recipe and the source it builds are
    colocated, so `path` also names the content root.  When the build is redirected, `path`
    describes the layout of the specs repo and says nothing about the source repo, so the
    content root stays at the source repo's root."""
    if stack_container.content_root:
        return stack_container.content_root
    if spec_ref and spec_ref not in (".", stack_container.ref):
        return None
    return stack_container.path


def read_stack_locks(stack_dir) -> dict:
    """Read the stack.lock beside a stack.yml: the pinned versions of the stack's build inputs.

    Format: {containers: {<container-name>: {ref, hash}}, wrappers: {<wrapper-name>: {ref, hash}}}.
    A legacy wrapper.lock is read as the wrappers section when no stack.lock exists."""
    locks = None
    lock_file_path = Path(stack_dir).joinpath(constants.stack_lock_file_name)
    if lock_file_path.exists():
        locks = get_yaml().load(open(lock_file_path, "r")) or {}
    else:
        legacy_lock_file_path = Path(stack_dir).joinpath(constants.wrapper_lock_file_name)
        if legacy_lock_file_path.exists():
            locks = {"wrappers": get_yaml().load(open(legacy_lock_file_path, "r")) or {}}
    if locks is None:
        locks = {}
    locks.setdefault("containers", {})
    locks.setdefault("wrappers", {})
    return locks


def write_stack_locks(stack_dir, locks: dict):
    lock_file_path = Path(stack_dir).joinpath(constants.stack_lock_file_name)
    with open(lock_file_path, "w") as output_file:
        get_yaml().dump({section: dict(pins) for section, pins in locks.items() if pins}, output_file)
    legacy_lock_file_path = Path(stack_dir).joinpath(constants.wrapper_lock_file_name)
    if legacy_lock_file_path.exists():
        log_info(f"{legacy_lock_file_path} has been superseded by {lock_file_path} and can be deleted.")


def read_container_locks(container_spec_dir) -> dict:
    """Read the container.lock beside a container.yml: {hash: <payload pin>, wrapper: {ref, hash}}."""
    lock_file_path = Path(container_spec_dir).joinpath(constants.container_lock_file_name)
    if lock_file_path.exists():
        return get_yaml().load(open(lock_file_path, "r")) or {}
    return {}


def recipe_repo_version(recipe_fs_path, lock_file_path=None):
    """The version (image tag) named by the recipe repo checkout: its HEAD hash when clean,
    a stackdev- hash otherwise.

    An existing but uncommitted (or modified) lock file also produces a stackdev- version,
    even though git does not count an untracked file as dirty: the pins it holds are not
    covered by the HEAD commit, so the HEAD hash alone would not reproduce the image.  The
    stackdev- hash is derived from the lock content, so it is stable across runs; committing
    the lock file is what stabilizes the version to a plain commit hash."""
    # Deferred import to avoid a circular dependency.
    from stack.repos.repo_util import get_container_tag_for_repo

    version = get_container_tag_for_repo(recipe_fs_path)
    if version and not version.startswith("stackdev-") and lock_file_path and Path(lock_file_path).exists():
        status = git.Repo(recipe_fs_path).git.status("--porcelain", str(lock_file_path))
        if status.strip():
            lock_digest = hashlib.sha1(open(lock_file_path, "rb").read()).hexdigest()
            version = "stackdev-" + hashlib.sha1(f"{version}:lock:{lock_digest}".encode()).hexdigest()
    return version


def same_repo_ref(ref_a, ref_b):
    if not ref_a or not ref_b:
        return False
    return ref_a.split("@")[0] == ref_b.split("@")[0]


def _embedded_pin(ref):
    # A ref of the form org/repo@<full-hash> pins that repo in the recipe file itself.
    if ref and "@" in ref:
        branch_or_hash = ref.split("@", 1)[1]
        if len(branch_or_hash) == 40 and all(c in string.hexdigits for c in branch_or_hash):
            return branch_or_hash
    return None


class ImageIdentity:
    """Where a container image's identity is anchored, and what that identity is.

    The image tag is the commit hash of the *recipe repo* -- the repo hosting the container's
    build declaration: the repo carrying its container.yml when there is one, otherwise the
    repo carrying the stack.yml that declares it.  Locks committed in the recipe repo
    (container.lock beside a container.yml, stack.lock beside a stack.yml) pin every other
    build input -- the payload source checkout and the wrapper -- so a clean recipe checkout
    fully determines image content.  That preserves the source<->image bijection when a build
    spans repos: the expected image registry, path and tag are computable from the recipe repo
    alone, and an image tag leads back through the recipe commit and its locks to every source
    commit that produced it.

    tag_version is the recipe repo's HEAD hash; a stackdev- hash when the recipe checkout is
    dirty; or None when there is no computable identity -- no recipe repo ref, or an input
    that is not yet pinned (unpinned is set in that case; building will generate the missing
    pins, and committing them stabilizes the identity)."""

    container_spec: "ContainerSpec"
    recipe_ref: str
    recipe_fs_path: Path
    tag_version: str
    unpinned: bool
    payload_ref: str
    payload_pin: str
    payload_is_recipe: bool
    wrapper_name: str
    wrapper_pin: dict
    stack_dir: Path
    container_lock_dir: Path
    lock_file_path: Path

    def __init__(self):
        self.container_spec = None
        self.recipe_ref = None
        self.recipe_fs_path = None
        self.tag_version = None
        self.unpinned = False
        self.payload_ref = None
        self.payload_pin = None
        self.payload_is_recipe = False
        self.wrapper_name = None
        self.wrapper_pin = None
        self.stack_dir = None
        self.container_lock_dir = None
        self.lock_file_path = None

    def __repr__(self):
        return str(self)

    def __str__(self):
        ret = {"recipe_ref": self.recipe_ref, "tag_version": self.tag_version, "unpinned": self.unpinned,
               "payload_ref": self.payload_ref, "payload_pin": self.payload_pin,
               "wrapper_name": self.wrapper_name, "wrapper_pin": self.wrapper_pin}
        return json.dumps(ret)


def compute_image_identity(stack, stack_container, dev_root_path) -> ImageIdentity:
    """Determine the recipe repo, pins and expected image tag for one stack container entry.

    Expects the repo named by stack_container.ref (if any) to be present locally already.
    May default stack_container.ref to the stack's own repo, mirroring the historic behavior."""
    # Deferred import to avoid a circular dependency.
    from stack.repos.repo_util import fs_path_for_repo

    # No container ref means use the stack repo.
    if (not stack_container.ref or stack_container.ref == ".") and stack and stack.get_repo_ref():
        stack_container.ref = stack.get_repo_ref()

    ident = ImageIdentity()
    container_spec = ContainerSpec(stack_container.name, stack_container.ref, path=stack_container.path,
                                   wrapper=stack_container.wrapper, wrapper_ref=stack_container.wrapper_ref,
                                   content_root=default_content_root(stack_container))

    spec_dir = None
    if stack_container.ref:
        # A ref naming the stack's own repo resolves to the tree the stack was actually
        # loaded from (which may be a checkout outside the dev root), so that identity
        # and content always come from the same tree.
        if stack and stack.repo_path and same_repo_ref(stack_container.ref, stack.get_repo_ref()):
            fs_path_for_container_specs = Path(stack.repo_path)
        else:
            fs_path_for_container_specs = Path(fs_path_for_repo(stack_container.ref, dev_root_path))
        candidate_dir = fs_path_for_container_specs
        if stack_container.path:
            candidate_dir = candidate_dir.joinpath(stack_container.path)
        if candidate_dir.joinpath(constants.container_file_name).exists():
            spec_dir = candidate_dir

    if spec_dir:
        # The ref'd repo hosts a container.yml: it is the recipe repo.
        container_spec = ContainerSpec(wrapper=stack_container.wrapper, wrapper_ref=stack_container.wrapper_ref,
                                       content_root=stack_container.content_root).init_from_file(
            spec_dir.joinpath(constants.container_file_name))
        if not container_spec.ref:
            # `ref` omitted in a container.yml means "the repo this descriptor lives in",
            # which is the repo the stack entry already named.
            container_spec.ref = stack_container.ref
        if not container_spec.content_root:
            container_spec.content_root = default_content_root(stack_container, container_spec.ref)
        ident.recipe_ref = stack_container.ref
        ident.recipe_fs_path = fs_path_for_container_specs
        ident.container_lock_dir = spec_dir
        ident.lock_file_path = spec_dir.joinpath(constants.container_lock_file_name)
        locks = read_container_locks(spec_dir)
        ident.payload_pin = locks.get("hash")
        ident.wrapper_pin = locks.get("wrapper")
    elif stack:
        # No container.yml: the stack.yml declaring the container is the recipe.
        ident.recipe_ref = stack.get_repo_ref()
        ident.recipe_fs_path = stack.repo_path
        if getattr(stack, "file_path", None) and stack.name != "None":
            ident.stack_dir = Path(stack.file_path).parent
            ident.lock_file_path = ident.stack_dir.joinpath(constants.stack_lock_file_name)
            if not ident.lock_file_path.exists():
                legacy_lock_file_path = ident.stack_dir.joinpath(constants.wrapper_lock_file_name)
                if legacy_lock_file_path.exists():
                    ident.lock_file_path = legacy_lock_file_path
            locks = read_stack_locks(ident.stack_dir)
            ident.payload_pin = locks["containers"].get(stack_container.name, {}).get("hash")
            if container_spec.wrapper:
                ident.wrapper_pin = locks["wrappers"].get(container_spec.wrapper)

    ident.container_spec = container_spec
    ident.payload_ref = container_spec.ref
    ident.wrapper_name = container_spec.wrapper
    ident.payload_is_recipe = same_repo_ref(ident.payload_ref, ident.recipe_ref)
    embedded_payload_pin = _embedded_pin(ident.payload_ref)
    if not ident.payload_pin:
        ident.payload_pin = embedded_payload_pin
    elif embedded_payload_pin and embedded_payload_pin != ident.payload_pin:
        error_exit(f"Hash in ref {ident.payload_ref} does not match locked hash {ident.payload_pin}.  Remove the lock file?")
    if not ident.wrapper_pin:
        embedded_wrapper_pin = _embedded_pin(container_spec.wrapper_ref)
        if embedded_wrapper_pin:
            ident.wrapper_pin = {"ref": container_spec.wrapper_ref.split("@")[0], "hash": embedded_wrapper_pin}

    payload_pinned = ident.payload_is_recipe or bool(ident.payload_pin)
    wrapper_pinned = not ident.wrapper_name or bool(ident.wrapper_pin)

    if ident.recipe_fs_path and Path(ident.recipe_fs_path).exists():
        version = recipe_repo_version(ident.recipe_fs_path, ident.lock_file_path)
        if version and not version.startswith("stackdev-") and not (payload_pinned and wrapper_pinned):
            # An unpinned input: the recipe commit does not determine image content,
            # so its hash must not be used as the image identity.
            ident.unpinned = True
            version = None
        ident.tag_version = version

    log_debug(f"Image identity for {stack_container.name}: {ident}")
    return ident


def get_containers_in_scope(stack):
    containers_in_scope = []
    if stack:
        if isinstance(stack, str):
            stack_config = stack_util.get_parsed_stack_config(stack)
        else:
            stack_config = stack
        raw_containers = stack_config.get("containers", [])
        if not raw_containers and not stack.is_super_stack():
            warn_exit(f"stack {stack} does not define any containers")
    else:
        # See: https://stackoverflow.com/a/20885799/1701505
        from stack import data
        with importlib.resources.open_text(data, "container-image-list.txt") as container_list_file:
            raw_containers = container_list_file.read().splitlines()

    for container in raw_containers:
        if isinstance(container, str):
            containers_in_scope.append(StackContainer(container))
        else:
            containers_in_scope.append(StackContainer(container["name"], ref=container.get("ref"), path=container.get("path"),
                                                      wrapper=container.get("wrapper"),
                                                      wrapper_ref=container.get("wrapper-ref"),
                                                      content_root=container.get("content-root")))

    log_debug(f"Containers: {containers_in_scope}")
    if stack:
        log_debug(f"Stack: {stack}")

    return containers_in_scope


def container_exists_locally(tag):
    docker = DockerClient()
    try:
        return docker.image.exists(tag)
    except Exception as e:
        if "image not known" in str(e):
            return False
        raise e


def container_exists_remotely(tag, registries=None, arch=None):
    if not arch:
        arch = local_container_arch()

    if not registries:
        registries = [None]
    else:
        registries.append(None)

    for registry in registries:
        manifests = _docker_manifest_inspect(tag, registry)
        for manifest in manifests:
            platform = manifest.get("Descriptor", {}).get("platform", {})
            if arch == platform.get("architecture") and "linux" == platform.get("os"):
                return True, registry

    return False, None


def _is_loopback_registry(registry):
    # A loopback registry speaks plain HTTP; docker treats it as implicitly insecure
    # for push/pull, but `manifest inspect` has to be told explicitly.
    if not registry:
        return False
    host = registry.split("/")[0].split(":")[0]
    return host in ("localhost", "127.0.0.1", "::1")


def _docker_manifest_inspect(tag, registry=None):
    manifest = None
    full_tag = tag
    if registry:
        full_tag = f"{registry}/{tag}"

    log_debug(f"Checking for {full_tag}")

    insecure_flag = "--insecure " if _is_loopback_registry(registry) else ""

    # Basic docker command
    manifest_cmd = ["docker", "manifest", "inspect"] + (["--insecure"] if insecure_flag else []) + ["--verbose", full_tag]

    # podman does not properly support the manifest command, so we cheat by having podman run the docker-cli
    docker_version = subprocess.run(["docker", "--version"], capture_output=True, text=True)
    if "podman" in docker_version.stdout:
        inspect_str = f"docker manifest inspect {insecure_flag}--verbose {full_tag}"
        if registry:
            username = None
            password = None
            registry_root = registry
            if "/" in registry:
                registry_root = registry.split("/")[0]
            if os.path.exists(f"{os.environ['XDG_RUNTIME_DIR']}/containers/auth.json"):
                auths = json.load(open(f"{os.environ['XDG_RUNTIME_DIR']}/containers/auth.json", "rt")).get("auths", {})
                login_info = None
                if registry in auths and "auth" in auths[registry]:
                    login_info = auths[registry]["auth"]
                elif registry_root in auths and "auth" in auths[registry_root]:
                    login_info = auths[registry_root]["auth"]
                if login_info:
                    username, password = base64.standard_b64decode(login_info).decode().split(":", 2)

            if username and password:
                inspect_str = (f'docker login --username "{username}" --password "{password}"'
                               f" {registry} >/dev/null && {inspect_str}")

        manifest_cmd = ["podman", "run", "-q", "alpinelinux/docker-cli", "sh", "-c", inspect_str]

    result = subprocess.run(manifest_cmd, capture_output=True, text=True)
    if 0 == result.returncode:
        manifest = json.loads(result.stdout)
        if not isinstance(manifest, list):
            manifest = [manifest]
    elif any(marker in result.stderr.lower() for marker in ("unauthorized", "authentication required", "denied", "401 ")):
        # Failing the check treats the image as not available remotely, which silently
        # forces a local build: make the reason visible. Registries generally return the
        # same denial for a private repo and one that does not exist, so we cannot tell
        # "not published" from "no access" here — say so rather than assuming a login is
        # needed, since the usual cause is simply that no image was ever published.
        log_warn(f"WARN: no pre-built image found at {registry or 'the default registry'} for {full_tag};"
                 f" building locally.  If it is private, log in first with: docker login {registry or ''}".rstrip())

    return manifest if manifest else []


def local_container_arch():
    this_machine = platform.machine()
    # Translate between Python and docker platform names
    if this_machine == "x86_64":
        this_machine = "amd64"
    if this_machine == "aarch64":
        this_machine = "arm64"
    return this_machine
