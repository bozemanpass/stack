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
import importlib.resources
import git
import json
import os
import platform
import subprocess

from pathlib import Path
from python_on_whales import DockerClient

import stack.deploy.stack as stack_util

from stack.log import log_debug
from stack.repos.repo_util import find_repo_root
from stack.util import warn_exit, get_yaml

class StackContainer:
    name: str
    ref: str
    path: str

    def __init__(self, name: str=None, ref=None, path=None):
        self.name = name
        self.ref = ref
        self.path = path

    def __repr__(self):
        return str(self)

    def __str__(self):
        ret = { "name": self.name, "ref": self.ref, "path": self.path }
        return json.dumps(ret)


class ContainerSpec:
    name: str
    ref: str
    build: str
    path: str
    file_path: str
    repo_path: Path

    def __init__(self, name: str=None, ref=None, build=None, path=None):
        self.name = name
        self.ref = ref
        self.build = build
        self.path = path
        self.file_path = None
        self.repo_path = None

    def __repr__(self):
        return str(self)

    def __str__(self):
        ret = { "name": self.name, "ref": self.ref, "build": self.build, "path": self.path, "file_path": self.file_path }
        return json.dumps(ret)

    def init_from_file(self, file_path: Path):
        self.file_path = Path(file_path).as_posix()
        self.path = Path(self.file_path).parent.as_posix()

        y = get_yaml().load(open(file_path, "r"))
        self.name = y["container"]["name"]
        self.ref = y["container"].get("ref")
        self.build = y["container"].get("build")
        self.repo_path = find_repo_root(self.path)
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


def get_containers_in_scope(stack):
    containers_in_scope = []
    if stack:
        if isinstance(stack, str):
            stack_config = stack_util.get_parsed_stack_config(stack)
        else:
            stack_config = stack
        if "containers" not in stack_config or stack_config["containers"] is None:
            warn_exit(f"stack {stack} does not define any containers")
        raw_containers = stack_config['containers']
    else:
        # See: https://stackoverflow.com/a/20885799/1701505
        from stack import data
        with importlib.resources.open_text(data, "container-image-list.txt") as container_list_file:
            raw_containers = container_list_file.read().splitlines()


    for container in raw_containers:
        if isinstance(container, str):
            containers_in_scope.append(StackContainer(container))
        else:
            containers_in_scope.append(StackContainer(container["name"], ref=container.get("ref"), path=container.get("path")))

    log_debug(f'Containers: {containers_in_scope}')
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


def _docker_manifest_inspect(tag, registry=None):
    manifest = None
    full_tag = tag
    if registry:
        full_tag = f"{registry}/{tag}"

    log_debug(f"Checking for {full_tag}")

    # Basic docker command
    manifest_cmd = ["docker", "manifest", "inspect", "--verbose", full_tag]

    # podman does not properly support the manifest command, so we cheat by having podman run the docker-cli
    docker_version = subprocess.run(["docker", "--version"], capture_output=True, text=True)
    if "podman" in docker_version.stdout:
        inspect_str = f"docker manifest inspect --verbose {full_tag}"
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
                inspect_str = f"""docker login --username "{username}" --password "{password}" {registry} >/dev/null && {inspect_str}"""

        manifest_cmd = ["podman", "run", "-q", "alpinelinux/docker-cli", "sh", "-c", inspect_str]

    result = subprocess.run(manifest_cmd, capture_output=True, text=True)
    if 0 == result.returncode:
        manifest = json.loads(result.stdout)
        if not isinstance(manifest, list):
            manifest = [manifest]

    return manifest if manifest else []


def local_container_arch():
    this_machine = platform.machine()
    # Translate between Python and docker platform names
    if this_machine == "x86_64":
        this_machine = "amd64"
    if this_machine == "aarch64":
        this_machine = "arm64"
    return this_machine
