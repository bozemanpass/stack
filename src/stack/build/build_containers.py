# Copyright © 2022, 2023 Vulcanize
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

# Builds or pulls containers for the system components

# env vars:
# STACK_REPO_BASE_DIR defaults to ~/.config/stack/repos

import click
import hashlib
import os

from pathlib import Path
from python_on_whales import DockerClient

from stack.base import get_npm_registry_url
from stack.build.build_types import BuildContext
from stack.build.build_util import (
    ContainerSpec,
    compute_image_identity,
    container_exists_locally,
    container_exists_remotely,
    get_containers_in_scope,
    local_container_arch,
    read_container_locks,
    read_stack_locks,
    recipe_repo_version,
    same_repo_ref,
    write_stack_locks,
)
from stack.build.publish import publish_image
from stack.build.wrappers import (
    fetch_default_wrapper_repos,
    fetch_wrapper_repo,
    resolve_wrapper,
    wrapper_repo_info,
)
from stack.config.util import get_config_setting, get_dev_root_path, debug_enabled
from stack.constants import container_lock_file_name
from stack.deploy.stack import get_parsed_stack_config, resolve_stack
from stack.log import log_info, log_debug, log_warn, output_main
from stack.opts import opts
from stack.repos.repo_util import image_registry_for_repo, fs_path_for_repo, process_repo, get_container_tag_for_repo
from stack.util import include_exclude_check, stack_is_external, error_exit, get_yaml
from stack.util import run_shell_command
from stack import constants

docker = DockerClient()

BUILD_POLICIES = [
    "as-needed",
    "build",
    "build-force",
    "prebuilt",
    "prebuilt-local",
    "prebuilt-remote",
]


# TODO: find a place for this
#    epilog="Config provided either in .env or settings.ini or env vars: STACK_REPO_BASE_DIR (defaults to ~/bpi)"


def make_container_build_env(dev_root_path: str, default_container_base_dir: str, force_rebuild: bool, extra_build_args: str):
    container_build_env = {
        "STACK_NPM_REGISTRY_URL": get_npm_registry_url(),
        "STACK_GO_AUTH_TOKEN": get_config_setting("STACK_GO_AUTH_TOKEN", default=""),
        "STACK_NPM_AUTH_TOKEN": get_config_setting("STACK_NPM_AUTH_TOKEN", default=""),
        "STACK_REPO_BASE_DIR": dev_root_path,
        "STACK_CONTAINER_BASE_DIR": default_container_base_dir,
        "STACK_HOST_UID": f"{os.getuid()}",
        "STACK_HOST_GID": f"{os.getgid()}",
        "STACK_IMAGE_LOCAL_TAG": "stack",
        "DOCKER_BUILDKIT": os.environ.get("DOCKER_BUILDKIT", default="1"),
    }
    container_build_env.update({"STACK_SCRIPT_DEBUG": "true"} if debug_enabled() else {})
    container_build_env.update({"STACK_FORCE_REBUILD": "true"} if force_rebuild else {})
    container_build_env.update({"STACK_CONTAINER_EXTRA_BUILD_ARGS": extra_build_args} if extra_build_args else {})
    docker_host_env = os.getenv("DOCKER_HOST")
    if docker_host_env:
        container_build_env.update({"DOCKER_HOST": docker_host_env})

    return container_build_env


def process_container(build_context: BuildContext) -> bool:

    building_container = build_context.container
    build_envs = build_context.container_build_env

    default_container_tag = f"{building_container.name}:stack"
    log_info(f"Processing build of container: {default_container_tag}")

    if building_container.wrapper:
        return _process_wrapped_container(build_context)

    build_envs.update({"STACK_FULL_CONTAINER_IMAGE_TAG": default_container_tag})
    build_envs.update({"STACK_DEFAULT_CONTAINER_IMAGE_TAG": default_container_tag})

    build_dir = None
    build_script_filename = None

    # A container spec (e.g. from a wrapper) may carry an absolute path to its build script.
    if building_container.build and Path(building_container.build).is_absolute():
        build_script_filename = Path(building_container.build)
        build_dir = build_script_filename.parent
        build_envs["STACK_BUILD_DIR"] = build_dir

    # Check if this is in an external stack
    # There may be no stack (stack.name == "None") when we build a bare container
    # DBDB we need to find where that name is getting set to the literal string "None"
    # because that ain't right.
    stack = build_context.stack
    if not build_dir and stack.name != "None" and stack_is_external(stack):
        log_debug(f"Determined stack: {stack.name} is external")
        # DBDB What is this code below doing?
        # "build" is pulled from the container description yaml
        # Presumably it means "the relative name of the build file"
        if building_container.build:
            # If the build script filename was provided, we use that
            build_script_filename = Path(building_container.file_path).parent.joinpath(building_container.build)
            build_dir = build_script_filename.parent
            build_envs["STACK_BUILD_DIR"] = build_dir
        else:
            # If the build script filename is not explicitly provided, we try to infer it
            # DBDB this code seems not to work because we use the bare stack name rather than a directory
            # We go looking for a "containers" directory in the root of the container's repo.
            container_build_script_dir = (fs_path_for_repo(building_container.ref)
                                          .joinpath(constants.stack_files_directory_name)
                                          .joinpath(constants.containers_directory_name))
            log_debug(f"Looking for build script in this directory: {container_build_script_dir}")
            if os.path.exists(container_build_script_dir):
                temp_build_dir = container_build_script_dir.joinpath(building_container.name.replace("/", "-"))
                temp_build_script_filename = temp_build_dir.joinpath("build.sh")
                # Now check if the container exists in the external stack.
                log_debug(f"Looking for build script at: {temp_build_script_filename}")
                if not temp_build_script_filename.exists():
                    # If not, revert to building an internal container
                    # DBDB Why?
                    container_build_script_dir = build_context.default_container_base_dir
                build_dir = container_build_script_dir.joinpath(building_container.name.replace("/", "-"))
                build_script_filename = build_dir.joinpath("build.sh")
                build_envs["STACK_BUILD_DIR"] = build_dir

    if not build_dir:
        build_dir = build_context.default_container_base_dir.joinpath(building_container.name.replace("/", "-"))
        build_script_filename = build_dir.joinpath("build.sh")

    log_debug(f"Build script filename: {build_script_filename}")
    log_debug(f"Build script filename: {build_dir}")

    if os.path.exists(build_script_filename):
        build_command = build_script_filename.as_posix()
    else:
        log_debug(f"No script file found: {build_script_filename}, using default build script")
        # The default build gets the source repo, narrowed to the content root, as its context.
        repo_full_path = _content_root_path(building_container, _source_repo_dir(building_container, stack))
        repo_dir_or_build_dir = repo_full_path if repo_full_path and repo_full_path.exists() else build_dir
        build_command = (
            os.path.join(build_context.default_container_base_dir, "default-build.sh")
            + f" {default_container_tag} {repo_dir_or_build_dir}"
        )
        build_envs["STACK_BUILD_DIR"] = repo_dir_or_build_dir

    build_envs["STACK_IMAGE_NAME"] = building_container.name

    build_envs["STACK_REPO_STACK_DIR"] = str(stack.repo_path) if stack.repo_path else ""
    build_envs["STACK_REPO_CONTAINER_DIR"] = (str(build_context.container.repo_path) if building_container.repo_path
                                              else build_envs["STACK_REPO_STACK_DIR"])
    build_envs["STACK_REPO_SOURCE_DIR"] = (str(fs_path_for_repo(building_container.ref)) if building_container.ref
                                           else build_envs["STACK_REPO_CONTAINER_DIR"])

    # The default build uses this as its context; a build script has to opt in, so hand it over.
    content_root_dir = _content_root_path(building_container, _source_repo_dir(building_container, stack))
    build_envs["STACK_CONTENT_ROOT_DIR"] = str(content_root_dir) if content_root_dir else build_envs["STACK_REPO_SOURCE_DIR"]

    if not opts.o.dry_run:
        # No PATH at all causes failures with podman.
        if "PATH" not in build_envs:
            build_envs["PATH"] = os.environ["PATH"]
        log_debug(f"Executing: {build_command} with environment: {build_envs}")

        build_result = run_shell_command(build_command, env=build_envs, quiet=opts.o.quiet or opts.o.quiet_build)

        log_debug(f"Build command return code is: {build_result}")
        if build_result != 0:
            return False
        else:
            return True
    else:
        log_info("Skipped for dry run")
        return True


def prepare_wrapper_base_container(wrapper, build_context: BuildContext) -> bool:
    """Make the wrapper's base container image available, tagged <base-container>:stack.

    A prebuilt image tagged with the wrapper repo's commit hash is used from the local
    store or pulled from the wrapper repo's image registry when possible; otherwise the
    base container is built locally."""
    force_rebuild = build_context.container_build_env.get("STACK_FORCE_REBUILD") == "true"
    stack_tag = f"{wrapper.base_container}:stack"

    wrapper_repo_ref, wrapper_hash, wrapper_repo_dirty = wrapper_repo_info(wrapper)
    hash_tag = f"{wrapper.base_container}:{wrapper_hash}" if wrapper_hash else None

    if hash_tag and not wrapper_repo_dirty and not force_rebuild:
        if container_exists_locally(hash_tag):
            log_info(f"Base container {hash_tag} exists locally.")
            docker.image.tag(hash_tag, stack_tag)
            return True
        if wrapper_repo_ref:
            registries = [r for r in [image_registry_for_repo(wrapper_repo_ref)] if r]
            exists_remotely, registry = container_exists_remotely(hash_tag, registries)
            if exists_remotely:
                pull_tag = f"{registry}/{hash_tag}" if registry else hash_tag
                log_info(f"Base container {pull_tag} exists remotely.")
                run_shell_command(f"docker pull {pull_tag}", quiet=opts.o.quiet or opts.o.quiet_build)
                if registry:
                    docker.image.tag(pull_tag, hash_tag)
                docker.image.tag(hash_tag, stack_tag)
                return True

    wrapper_build_script = str(wrapper.build_script_path()) if wrapper.build_script_path().exists() else None
    base_context = BuildContext(
        build_context.stack,
        ContainerSpec(wrapper.base_container, build=wrapper_build_script),
        build_context.default_container_base_dir,
        dict(build_context.container_build_env),
        build_context.dev_root_path,
    )
    ok = process_container(base_context)
    if ok and hash_tag and not wrapper_repo_dirty:
        # Tag the local build with the hash so subsequent builds skip this step.
        docker.image.tag(stack_tag, hash_tag)
    return ok


def _resolve_wrapper_for_container(building_container, wrapper_pin: dict):
    wrapper_name = building_container.wrapper
    wrapper_ref = building_container.wrapper_ref or wrapper_pin.get("ref")
    locked_hash = wrapper_pin.get("hash")

    if wrapper_ref:
        # An explicit (or locked) wrapper repo: fetch it and resolve only within it.
        fetch_ref = wrapper_ref
        if locked_hash:
            fetch_ref = f"{wrapper_ref.split('@')[0]}@{locked_hash}"
        repo_fs_path = fetch_wrapper_repo(fetch_ref)
        wrapper = resolve_wrapper(wrapper_name, search_root=repo_fs_path)
        if not wrapper:
            error_exit(f"Wrapper {wrapper_name} not found in {wrapper_ref} for container: {building_container.name}")
        return wrapper

    wrapper = resolve_wrapper(wrapper_name)
    if not wrapper:
        fetch_default_wrapper_repos()
        wrapper = resolve_wrapper(wrapper_name)
    if not wrapper:
        error_exit(f"Unknown wrapper {wrapper_name} for container: {building_container.name}")
    return wrapper


def _source_repo_dir(building_container, stack):
    """The repo whose source this container is built from.

    `ref` names it.  A ref naming the stack's own repo resolves to the tree the stack was
    loaded from (possibly a checkout outside the dev root), keeping the built content and
    the image identity in the same tree.  A container.yml that omits `ref` means "the repo
    this descriptor lives in", which is what `repo_path` records.  Failing both, the
    stack's own repo."""
    if building_container.ref:
        if stack is not None and getattr(stack, "repo_path", None) and same_repo_ref(building_container.ref, stack.get_repo_ref()):
            return stack.repo_path
        return fs_path_for_repo(building_container.ref)
    if building_container.repo_path:
        return building_container.repo_path
    return stack.repo_path


def _content_root_path(building_container, source_dir):
    """`source_dir` narrowed to the container's content root.

    The content root is the subdirectory of the source repo that is actually built (wrapped,
    or handed to the default build as its context).  It defaults to the whole repo.  See the
    ContainerSpec docstring for how it differs from `path`."""
    if not source_dir:
        return source_dir
    content_root = str(building_container.content_root or ".").lstrip("/")
    return Path(source_dir).joinpath(content_root)


def _process_wrapped_container(build_context: BuildContext) -> bool:
    building_container = build_context.container
    stack = build_context.stack

    wrapper = _resolve_wrapper_for_container(building_container, build_context.notes.get("wrapper_pin") or {})

    log_info(f"Building {building_container.name} using wrapper: {wrapper.name}")

    # Report the wrapper version actually used, so the caller can compare it
    # against the pin and record a missing pin after a successful build.
    wrapper_repo_ref, wrapper_hash, wrapper_repo_dirty = wrapper_repo_info(wrapper)
    build_context.notes["wrapper"] = {
        "name": building_container.wrapper,
        "ref": building_container.wrapper_ref or wrapper_repo_ref,
        "hash": wrapper_hash,
        "dirty": wrapper_repo_dirty,
    }

    if not prepare_wrapper_base_container(wrapper, build_context):
        return False

    wrapper_build_script = str(wrapper.build_script_path()) if wrapper.build_script_path().exists() else None

    # Now wrap the app source, using the same build script but with the
    # wrapper's containerfile and the app source repo as the build context.
    app_source_dir = _content_root_path(building_container, _source_repo_dir(building_container, stack))
    if not app_source_dir or not app_source_dir.exists():
        error_exit(f"Content root {app_source_dir} for container {building_container.name} does not exist.")

    app_build_env = dict(build_context.container_build_env)
    app_build_env["STACK_WEBAPP_BUILD_RUNNING"] = "true"
    app_build_env["STACK_CONTAINER_BUILD_WORK_DIR"] = str(app_source_dir)
    app_build_env["STACK_CONTAINER_BUILD_CONTAINERFILE"] = str(wrapper.containerfile_path())
    app_build_env["STACK_CONTAINER_BUILD_TAG"] = f"{building_container.name}:stack"

    app_context = BuildContext(
        build_context.stack,
        ContainerSpec(building_container.name, build=wrapper_build_script),
        build_context.default_container_base_dir,
        app_build_env,
        build_context.dev_root_path,
    )
    return process_container(app_context)


def _write_missing_pins(identity, payload_version, wrapper_used):
    """After a successful build, record any input pins the recipe repo was missing.

    Only clean, reproducible versions are ever pinned.  Writing a pin dirties the recipe
    repo, so images built before the pins are committed keep a stackdev identity;
    committing the lock file is what stabilizes the image tag."""
    if opts.o.dry_run:
        return

    payload_pin_needed = (identity.payload_ref and not identity.payload_is_recipe and not identity.payload_pin
                          and payload_version and not payload_version.startswith("stackdev-"))
    wrapper_pin_needed = bool(wrapper_used and not identity.wrapper_pin and wrapper_used.get("hash")
                              and not wrapper_used.get("dirty") and wrapper_used.get("ref"))
    if wrapper_used and wrapper_used.get("dirty"):
        log_warn(f"WARN: wrapper repo for {wrapper_used['name']} has local modifications, not locking.")
    if not (payload_pin_needed or wrapper_pin_needed):
        return

    if identity.stack_dir:
        locks = read_stack_locks(identity.stack_dir)
        if payload_pin_needed:
            locks["containers"][identity.container_spec.name] = {"ref": identity.payload_ref.split("@")[0], "hash": payload_version}
            log_info(f"Locking {identity.container_spec.name} payload to {payload_version}")
        if wrapper_pin_needed:
            locks["wrappers"][wrapper_used["name"]] = {"ref": wrapper_used["ref"].split("@")[0], "hash": wrapper_used["hash"]}
            log_info(f"Locking wrapper {wrapper_used['name']} to {wrapper_used['hash']}")
        write_stack_locks(identity.stack_dir, locks)
    elif identity.container_lock_dir:
        locks = read_container_locks(identity.container_lock_dir)
        if payload_pin_needed:
            locks["hash"] = payload_version
            log_info(f"Locking {identity.container_spec.name} payload to {payload_version}")
        if wrapper_pin_needed:
            locks["wrapper"] = {"ref": wrapper_used["ref"].split("@")[0], "hash": wrapper_used["hash"]}
            log_info(f"Locking wrapper {wrapper_used['name']} to {wrapper_used['hash']}")
        lock_file_path = Path(identity.container_lock_dir).joinpath(container_lock_file_name)
        with open(lock_file_path, "w") as output_file:
            log_info(f"Writing lock file {lock_file_path}")
            get_yaml().dump(locks, output_file)


def build_containers(parent_stack,  # noqa: C901
                     build_policy=get_config_setting("build-policy", BUILD_POLICIES[0]),
                     image_registry=get_config_setting("image-registry"),
                     publish_images=get_config_setting("publish-images", False),
                     include=None,
                     exclude=None,
                     extra_build_args=None,
                     git_ssh=get_config_setting("git-ssh", False),
                     git_pull=False,
                     dont_pull_repo_fs_paths=None,
                     target_arch=None,
                     dont_pull_images=False):
    dev_root_path = get_dev_root_path()
    required_stacks = parent_stack.get_required_stacks_paths()
    if not dont_pull_repo_fs_paths:
        dont_pull_repo_fs_paths = []

    all_containers_in_scope = []
    finished_containers = {}
    for stack in required_stacks:
        stack = get_parsed_stack_config(stack)
        containers_in_scope = [c for c in get_containers_in_scope(stack) if include_exclude_check(c.name, include, exclude)]
        all_containers_in_scope.extend(containers_in_scope)

    log_info(f"Found {len(all_containers_in_scope)} containers in {len(required_stacks)} stacks: "
             f"{', '.join([c.name for c in all_containers_in_scope])}", bold=True)

    for stack in required_stacks:
        stack = get_parsed_stack_config(stack)

        if build_policy not in BUILD_POLICIES:
            error_exit(f"{build_policy} is not one of {BUILD_POLICIES}")

        # See: https://stackoverflow.com/questions/25389095/python-get-path-of-root-project-structure
        default_container_base_dir = Path(__file__).absolute().parent.parent.joinpath("data", "container-build")

        log_debug("Dev Root is: {dev_root_path}")

        if not os.path.isdir(dev_root_path):
            log_debug("Dev root directory doesn't exist, creating")

        if target_arch and target_arch != local_container_arch():
            if not dont_pull_images:
                error_exit("--target-arch requires --dont-pull-images")
            if build_policy != "prebuilt-remote":
                error_exit("--target-arch requires --build-policy prebuilt-remote")

        # check if we have any repos that specify the container targets / build info
        containers_in_scope = [c for c in get_containers_in_scope(stack) if include_exclude_check(c.name, include, exclude)]
        for stack_container in containers_in_scope:

            log_info(f"Preparing {stack_container.name} ({len(finished_containers)+1} of {len(all_containers_in_scope)})",
                     bold=True)

            # No container ref means use the stack repo.
            if (not stack_container.ref or stack_container.ref == ".") and stack.get_repo_ref():
                stack_container.ref = stack.get_repo_ref()

            if stack_container.ref and not (
                stack.repo_is_local_checkout() and same_repo_ref(stack_container.ref, stack.get_repo_ref())
            ):
                fs_path_for_container_specs = fs_path_for_repo(stack_container.ref, dev_root_path)
                if not os.path.exists(fs_path_for_container_specs) or (
                        git_pull and fs_path_for_container_specs not in dont_pull_repo_fs_paths):
                    process_repo(git_pull, False, git_ssh, dev_root_path, [], stack_container.ref)
                    dont_pull_repo_fs_paths.append(fs_path_for_container_specs)

            # The image is identified by the recipe repo's commit hash, with locks in the
            # recipe repo pinning the other build inputs (see ImageIdentity).
            identity = compute_image_identity(stack, stack_container, dev_root_path)
            container_spec = identity.container_spec

            container_needs_built = True
            container_was_built = False
            container_was_pulled = False
            container_needs_pulled = False
            container_tag = f"{container_spec.name}:{identity.tag_version}"[:128] if identity.tag_version else None
            stack_local_tag = f"{container_spec.name}:stack"
            stack_legacy_tag = f"{container_spec.name}:local"
            image_registry_to_pull_this_container = image_registry
            image_registry_to_push_this_container = image_registry
            image_registries_to_check = [r for r in [image_registry, image_registry_for_repo(identity.recipe_ref)] if r]

            if container_tag:
                exists_locally = container_exists_locally(container_tag)
                if exists_locally and build_policy in ["as-needed", "prebuilt", "prebuilt-local"]:
                    log_info(f"Container {container_tag} exists locally.")
                    container_needs_pulled = False
                    container_needs_built = False
                    # Tag the local copy to point at it.
                    docker.image.tag(container_tag, stack_local_tag)
                elif not identity.tag_version.startswith("stackdev-"):
                    # A stackdev version is never published, so don't look for it remotely.
                    if build_policy in ["as-needed", "prebuilt", "prebuilt-remote"]:
                        exists_remotely, image_registry_to_pull_this_container = container_exists_remotely(
                            container_tag, image_registries_to_check, target_arch)
                        if exists_remotely:
                            if image_registry_to_pull_this_container:
                                log_info(f"Container {image_registry_to_pull_this_container}/{container_tag} exists remotely.")
                            else:
                                log_info(f"Container {container_tag} exists remotely.")
                            container_needs_pulled = not dont_pull_images
                            container_needs_built = False
            elif identity.unpinned:
                log_info(f"Container {container_spec.name} has unpinned build inputs, so it must be built.")

            if container_needs_pulled:
                # Pull the remote image
                if image_registry_to_pull_this_container:
                    run_shell_command(f"docker pull {image_registry_to_pull_this_container}/{container_tag}",
                                      quiet=opts.o.quiet or opts.o.quiet_build)
                    # Tag the local copy to point at it.
                    docker.image.tag(f"{image_registry_to_pull_this_container}/{container_tag}", container_tag)
                else:
                    run_shell_command(f"docker pull {container_tag}", quiet=opts.o.quiet or opts.o.quiet_build)
                # Tag the local copy to point at it.
                docker.image.tag(container_tag, stack_local_tag)
                container_was_pulled = True
            elif container_needs_built:
                if build_policy in ["prebuilt", "prebuilt-local", "prebuilt-remote"]:
                    error_exit(f"No prebuilt image available for: {container_spec.name}")

                if container_tag:
                    log_info(f"Container {container_tag} needs to be built.")

                # Make sure the payload source is present, at the pinned version when there is one.
                payload_version = None
                deviating_inputs = []
                if identity.payload_ref:
                    if identity.payload_is_recipe:
                        # Colocated: the recipe tree is the payload source; it is already
                        # present and its state is already reflected in the identity.
                        target_fs_repo_path = identity.recipe_fs_path
                        log_info(f"Building {container_spec.name} from {target_fs_repo_path}")
                    else:
                        target_fs_repo_path = fs_path_for_repo(identity.payload_ref, dev_root_path)
                        if not os.path.exists(target_fs_repo_path) or (
                                git_pull and target_fs_repo_path not in dont_pull_repo_fs_paths):
                            fetch_ref = identity.payload_ref
                            if identity.payload_pin:
                                fetch_ref = f"{identity.payload_ref.split('@')[0]}@{identity.payload_pin}"
                            process_repo(git_pull, False, git_ssh, dev_root_path, [], fetch_ref)
                            dont_pull_repo_fs_paths.append(target_fs_repo_path)
                        else:
                            log_info(f"Building {container_spec.name} from {target_fs_repo_path}")
                    payload_version = get_container_tag_for_repo(target_fs_repo_path)
                    if not identity.payload_is_recipe:
                        if not identity.payload_pin:
                            deviating_inputs.append(f"payload:{payload_version}")
                        elif payload_version != identity.payload_pin:
                            log_warn(f"WARN: {identity.payload_ref} checkout {payload_version} "
                                     f"does not match locked hash {identity.payload_pin}.", bold=True)
                            deviating_inputs.append(f"payload:{payload_version}")

                container_build_env = make_container_build_env(
                    dev_root_path, default_container_base_dir, "build-force" == build_policy, extra_build_args
                )

                build_context = BuildContext(stack, container_spec, default_container_base_dir, container_build_env, dev_root_path)
                build_context.notes["wrapper_pin"] = identity.wrapper_pin

                for tag in [stack_legacy_tag, stack_local_tag, container_tag]:
                    if not tag:
                        continue
                    try:
                        docker.image.remove(tag)
                    except Exception:
                        pass

                result = process_container(build_context)
                if not result:
                    error_exit(f"container build failed for: {build_context.container}")

                container_was_built = True
                # Handle legacy build scripts
                if container_exists_locally(stack_legacy_tag) and not container_exists_locally(stack_local_tag):
                    docker.image.tag(stack_legacy_tag, stack_local_tag)

                wrapper_used = build_context.notes.get("wrapper")
                if wrapper_used:
                    if not identity.wrapper_pin:
                        deviating_inputs.append(f"wrapper:{wrapper_used['hash']}{'-dirty' if wrapper_used['dirty'] else ''}")
                    elif wrapper_used["dirty"] or (
                            wrapper_used["hash"] and wrapper_used["hash"] != identity.wrapper_pin.get("hash")):
                        log_warn(f"WARN: wrapper {wrapper_used['name']} at {wrapper_used['hash']} "
                                 f"does not match locked hash {identity.wrapper_pin.get('hash')}.", bold=True)
                        deviating_inputs.append(f"wrapper:{wrapper_used['hash']}{'-dirty' if wrapper_used['dirty'] else ''}")

                # The actual inputs are known now, so settle the image identity.
                if identity.recipe_fs_path and Path(identity.recipe_fs_path).exists():
                    built_version = recipe_repo_version(identity.recipe_fs_path, identity.lock_file_path)
                    if deviating_inputs:
                        # The content deviates from what the recipe commit pins, so the recipe
                        # hash must not name it: generate a dev version from the actual inputs.
                        built_version = "stackdev-" + hashlib.sha1(
                            ":".join([built_version] + deviating_inputs).encode()).hexdigest()
                        log_warn(f"WARN: {container_spec.name} was built from unpinned or deviating inputs."
                                 f"  Using generated version: {built_version}", bold=True)
                    container_tag = f"{container_spec.name}:{built_version}"[:128]

                _write_missing_pins(identity, payload_version, wrapper_used)

            if container_tag:
                # We won't have a local copy with prebuilt-remote and --no-pull
                if container_exists_locally(stack_local_tag) and container_was_built:
                    # Point the local copy at the expected name.
                    docker.image.tag(stack_local_tag, container_tag)

                # Now check the other way, we have the container_tag but not the local tags
                if container_exists_locally(container_tag):
                    if not container_exists_locally(stack_local_tag):
                        docker.image.tag(container_tag, stack_local_tag)
                    if not container_exists_locally(stack_legacy_tag):
                        docker.image.tag(container_tag, stack_legacy_tag)

            if publish_images and container_tag:
                if not image_registry_to_push_this_container:
                    error_exit(f"No image registry specified to push {container_tag}")
                container_version = container_tag.split(":")[-1]
                if container_version.startswith("stackdev-"):
                    log_warn(f"WARN: not publishing {container_tag}: it was not built from committed, pinned inputs.", bold=True)
                else:
                    log_info(f"Publishing {container_tag} to {image_registry_to_push_this_container}")
                    publish_image(stack_local_tag, image_registry_to_push_this_container, container_version)

            log_debug(f"Finished {container_spec.name} ({len(finished_containers)+1} of {len(all_containers_in_scope)})", bold=True)
            final_status = "built" if container_was_built else "pulled" if container_was_pulled else "existing-image"
            finished_containers[container_spec.name] = final_status

    log_info(f"Prepared {len(finished_containers)} containers:")
    max_name_len = 0
    for name in finished_containers.keys():
        max_name_len = max(max_name_len, len(name))

    padding = 8
    for name, status in finished_containers.items():
        output_main(f"{name.ljust(max_name_len + padding)} {status}")


@click.command()
@click.option("--stack", help="name or path of the stack", required=False)
@click.option("--include", help="only build these containers")
@click.option("--exclude", help="don't build these containers")
@click.option("--git-ssh/--no-git-ssh", is_flag=True, default=get_config_setting("git-ssh", False),
              help="use SSH for git rather than HTTPS")
@click.option("--build-policy", default=BUILD_POLICIES[0], help=f"Available policies: {BUILD_POLICIES}")
@click.option("--extra-build-args", help="Supply extra arguments to build")
@click.option("--dont-pull-images", is_flag=True, default=False, help="Don't pull remote images (useful with k8s deployments).")
@click.option("--publish-images", is_flag=True, default=False, help="Publish the built images")
@click.option("--image-registry", help="Specify the remote image registry (default: auto-detect per-container)",
              default=get_config_setting("image-registry"))
@click.option("--target-arch", help="Specify a target architecture (only for use with --dont-pull-images)")
@click.pass_context
def command(ctx, stack, include, exclude, git_ssh, build_policy, extra_build_args, dont_pull_images, publish_images,
            image_registry, target_arch):
    """build stack containers"""
    stack = resolve_stack(stack)
    build_containers(stack,
                     build_policy,
                     image_registry,
                     publish_images,
                     include,
                     exclude,
                     extra_build_args,
                     git_ssh,
                     False,
                     [],
                     target_arch,
                     dont_pull_images)
