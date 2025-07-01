# Copyright © 2022, 2023 Vulcanize
# Copyright © 2025 Bozeman Pass, Inc.
import sys

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
# STACK_REPO_BASE_DIR defaults to ~/bpi

import click
import json
import git
import os

from pathlib import Path

from python_on_whales import DockerClient

from stack import constants
from stack.config.util import get_config_setting, get_dev_root_path, debug_enabled
from stack.base import get_npm_registry_url
from stack.build.build_types import BuildContext
from stack.build.build_util import ContainerSpec, get_containers_in_scope, container_exists_locally, container_exists_remotely, local_container_arch
from stack.build.publish import publish_image
from stack.constants import container_file_name, container_lock_file_name, stack_file_name
from stack.deploy.stack import Stack, get_parsed_stack_config, resolve_stack
from stack.opts import opts
from stack.repos.repo_util import host_and_path_for_repo, image_registry_for_repo, fs_path_for_repo, process_repo
from stack.util import include_exclude_check, stack_is_external, error_exit, get_yaml, check_if_stack_exists
from stack.repos.repo_util import clone_all_repos_for_stack

from stack.log import log_error, log_info, log_debug, log_warn, output_main, is_info_enabled

from stack.util import run_shell_command

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
        "DOCKER_BUILDKIT": os.environ.get("DOCKER_BUILDKIT", default="0"),
    }
    container_build_env.update({"STACK_SCRIPT_DEBUG": "true"} if debug_enabled() else {})
    container_build_env.update({"STACK_FORCE_REBUILD": "true"} if force_rebuild else {})
    container_build_env.update({"STACK_CONTAINER_EXTRA_BUILD_ARGS": extra_build_args} if extra_build_args else {})
    docker_host_env = os.getenv("DOCKER_HOST")
    if docker_host_env:
        container_build_env.update({"DOCKER_HOST": docker_host_env})

    return container_build_env


def process_container(build_context: BuildContext) -> bool:
    log_info(f"Building: {build_context.container.name}:stack")

    default_container_tag = f"{build_context.container.name}:stack"
    build_context.container_build_env.update({"STACK_DEFAULT_CONTAINER_IMAGE_TAG": default_container_tag})

    build_dir = None
    build_script_filename = None

    # Check if this is in an external stack
    if stack_is_external(build_context.stack):
        if build_context.container.build:
            build_script_filename = Path(build_context.container.file_path).parent.joinpath(build_context.container.build)
            build_dir = build_script_filename.parent
            build_context.container_build_env["STACK_BUILD_DIR"] = build_dir
        else:
            container_build_script_dir = Path(build_context.stack.name).parent.parent.joinpath("container-build")
            if os.path.exists(container_build_script_dir):
                temp_build_dir = container_build_script_dir.joinpath(build_context.container.name.replace("/", "-"))
                temp_build_script_filename = temp_build_dir.joinpath("build.sh")
                # Now check if the container exists in the external stack.
                if not temp_build_script_filename.exists():
                    # If not, revert to building an internal container
                    container_build_script_dir = build_context.default_container_base_dir
                build_dir = container_build_script_dir.joinpath(build_context.container.name.replace("/", "-"))
                build_script_filename = build_dir.joinpath("build.sh")
                build_context.container_build_env["STACK_BUILD_DIR"] = build_dir
    if not build_dir:
        build_dir = build_context.default_container_base_dir.joinpath(build_context.container.name.replace("/", "-"))
        build_script_filename = build_dir.joinpath("build.sh")

    log_debug(f"Build script filename: {build_script_filename}")

    if os.path.exists(build_script_filename):
        build_command = build_script_filename.as_posix()
    else:
        log_debug(f"No script file found: {build_script_filename}, using default build script")
        if build_context.container.ref:
            repo_full_path = fs_path_for_repo(build_context.container.ref)
        else:
            repo_full_path = build_context.stack.repo_path

        if build_context.container.path:
            repo_full_path = repo_full_path.joinpath(build_context.container.path)
        repo_dir_or_build_dir = repo_full_path if repo_full_path.exists() else build_dir
        build_command = (
            os.path.join(build_context.default_container_base_dir, "default-build.sh")
            + f" {default_container_tag} {repo_dir_or_build_dir}"
        )
        build_context.container_build_env["STACK_BUILD_DIR"] = repo_dir_or_build_dir


    build_context.container_build_env["STACK_IMAGE_NAME"] = build_context.container.name
    if not opts.o.dry_run:
        # No PATH at all causes failures with podman.
        if "PATH" not in build_context.container_build_env:
            build_context.container_build_env["PATH"] = os.environ["PATH"]
        log_debug(f"Executing: {build_command} with environment: {build_context.container_build_env}")

        build_result = run_shell_command(build_command, env=build_context.container_build_env, quiet=opts.o.quiet)

        log_debug(f"Return code is: {build_result}")
        if build_result != 0:
            return False
        else:
            return True
    else:
        log_info("Skipped")
        return True



def build_containers(parent_stack,
                     build_policy=get_config_setting("build-policy", BUILD_POLICIES[0]),
                     image_registry=get_config_setting("image-registry"),
                     publish_images=get_config_setting("publish-images", False),
                     include=None,
                     exclude=None,
                     extra_build_args=None,
                     git_ssh=get_config_setting("git-ssh", False),
                     target_arch=None,
                     dont_pull_images=False):
    dev_root_path = get_dev_root_path()
    required_stacks = parent_stack.get_required_stacks_paths()

    all_containers_in_scope = []
    finished_containers = {}
    for stack in required_stacks:
        stack = get_parsed_stack_config(stack)
        containers_in_scope = [c for c in get_containers_in_scope(stack) if include_exclude_check(c.name, include, exclude)]
        all_containers_in_scope.extend(containers_in_scope)

    log_info(f"Found {len(all_containers_in_scope)} containers in {len(required_stacks)} stacks: {", ".join([c.name for c in all_containers_in_scope])}", bold=True)

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


        container_build_env = make_container_build_env(
            dev_root_path, default_container_base_dir, "build-force" == build_policy, extra_build_args
        )

        # check if we have any repos that specify the container targets / build info
        containers_in_scope = [c for c in get_containers_in_scope(stack) if include_exclude_check(c.name, include, exclude)]
        for stack_container in containers_in_scope:
            # No container ref means use the stack repo.
            if (not stack_container.ref or stack_container.ref == ".") and stack.get_repo_ref():
                stack_container.ref = stack.get_repo_ref()

            container_needs_built = True
            container_was_built = False
            container_was_pulled = False
            container_needs_pulled = False
            container_tag = None
            container_spec = ContainerSpec(stack_container.name, stack_container.ref, path=stack_container.path)
            stack_local_tag = f"{container_spec.name}:stack"
            stack_legacy_tag = f"{container_spec.name}:local"
            image_registry_to_pull_this_container = image_registry
            image_registry_to_push_this_container = image_registry

            log_info(f"Preparing {container_spec.name} ({len(finished_containers)+1} of {len(all_containers_in_scope)})", bold=True)

            if stack_container.ref:
                fs_path_for_container_specs = fs_path_for_repo(stack_container.ref, dev_root_path)
                if not os.path.exists(fs_path_for_container_specs):
                    process_repo(False, False, git_ssh, dev_root_path, [], stack_container.ref)

                image_registries_to_check = [r for r in [image_registry, image_registry_for_repo(stack_container.ref)] if r]

                container_spec_yml_path = os.path.join(fs_path_for_container_specs, container_file_name)
                container_lock_file_path = os.path.join(fs_path_for_container_specs, container_lock_file_name)
                if stack_container.path:
                    container_spec_yml_path = os.path.join(fs_path_for_container_specs, stack_container.path, container_file_name)
                    container_lock_file_path = os.path.join(fs_path_for_container_specs, stack_container.path, container_lock_file_name)

                if os.path.exists(container_spec_yml_path):
                    container_spec = ContainerSpec().init_from_file(container_spec_yml_path)

                if container_spec.ref:
                    locked_hash = None
                    if os.path.exists(container_lock_file_path):
                        locked_hash = get_yaml().load(open(container_lock_file_path, "r")).get("hash")

                    target_hash = locked_hash
                    repo_host, repo_path, branch_or_hash_from_spec = host_and_path_for_repo(container_spec.ref)
                    repo = f"https://{repo_host}/{repo_path}"
                    if git_ssh:
                        repo = f"git@{repo_host}:{repo_path}"
                    target_fs_repo_path = fs_path_for_repo(container_spec.ref, dev_root_path)
                    # does the ref include a hash?
                    if (
                            branch_or_hash_from_spec
                            and len(branch_or_hash_from_spec) == 40
                            and all(c in string.hexdigits for c in branch_or_hash_from_spec)
                    ):
                        if not locked_hash:
                            target_hash = branch_or_hash_from_spec
                        elif locked_hash != branch_or_hash_from_spec:
                            error_exit(
                                f"Specified hash {target_hash} does not match locked hash {locked_hash}.  Remove {container_lock_file_path}?"
                            )
                    else:
                        git_client = git.cmd.Git()
                        result = git_client.ls_remote(repo, branch_or_hash_from_spec)
                        if result:
                            git_hash = result.split()[0]
                            if locked_hash:
                                if git_hash != locked_hash:
                                    log_warn(
                                        f"WARN: Locked hash {locked_hash} from {container_lock_file_path} does not match remote hash {git_hash} for {container_spec.ref}."
                                    )
                            else:
                                target_hash = git_hash

                    if not os.path.exists(container_lock_file_path):
                        with open(container_lock_file_path, "w") as output_file:
                            get_yaml().dump({"hash": target_hash}, output_file)

                    container_tag = f"{container_spec.name}:{target_hash}"[:128]
                    exists_remotely = None
                    exists_locally = container_exists_locally(container_tag)

                    if exists_locally and build_policy in ["as-needed", "prebuilt", "prebuilt-local"]:
                        log_info(f"Container {container_tag} exists locally.")
                        container_needs_pulled = False
                        container_needs_built = False
                        # Tag the local copy to point at it.
                        docker.image.tag(container_tag, stack_local_tag)
                    else:
                        if build_policy in [ "as-needed", "prebuilt", "prebuilt-remote", ]:
                            exists_remotely, image_registry_to_pull_this_container = container_exists_remotely(container_tag, image_registries_to_check, target_arch)
                            if exists_remotely:
                                if image_registry_to_pull_this_container:
                                    log_info(f"Container {image_registry_to_pull_this_container}:{container_tag} exists remotely.")
                                else:
                                    log_info(f"Container {container_tag} exists remotely.")
                                container_needs_pulled = not dont_pull_images
                                container_needs_built = False

                    if container_needs_built:
                        if build_policy in ["prebuilt", "prebuilt-local", "prebuilt-remote"]:
                            error_exit(f"Container {container_tag} not available prebuilt.")
                        else:
                            log_info(f"Container {container_tag} needs to be built.")
                            container_needs_pulled = False
                            container_needs_built = True
                            if not os.path.exists(target_fs_repo_path):
                                reconstructed_ref = f"{container_spec.ref.split('@')[0]}@{target_hash}"
                                process_repo(False, False, git_ssh, dev_root_path, [], reconstructed_ref)
                            else:
                                log_info(
                                    f"Building {container_tag} from {target_fs_repo_path}\n\t"
                                    "IMPORTANT: source files may include changes or be on a different branch than specified in container.yml."
                                )

            if container_needs_pulled:
                if not container_tag:
                    error_exit(f"Cannot pull container: tag missing.")
                # Pull the remote image
                if image_registry_to_pull_this_container:
                    run_shell_command(f"docker pull {image_registry_to_pull_this_container}/{container_tag}", quiet=opts.o.quiet)
                    # Tag the local copy to point at it.
                    docker.image.tag(f"{image_registry_to_pull_this_container}/{container_tag}", container_tag)
                else:
                    run_shell_command(f"docker pull {container_tag}", quiet=opts.o.quiet)
                # Tag the local copy to point at it.
                docker.image.tag(container_tag, stack_local_tag)
                container_was_pulled = True
            elif container_needs_built:
                if build_policy in ["prebuilt", "prebuilt-local", "prebuilt-remote"]:
                    error_exit(f"No prebuilt image available for: {container_spec.name}")

                build_context = BuildContext(stack, container_spec, default_container_base_dir, container_build_env, dev_root_path)

                for tag in [stack_legacy_tag, stack_local_tag, container_tag]:
                    try:
                        docker.image.remove(tag)
                    except:
                        pass

                log_info(f"Building {container_spec.name}")
                result = process_container(build_context)
                if result:
                    container_was_built = True
                    # Handle legacy build scripts
                    if container_exists_locally(stack_legacy_tag) and not container_exists_locally(stack_local_tag):
                        docker.image.tag(stack_legacy_tag, stack_local_tag)
                else:
                    error_exit(f"container build failed for: {build_context.container}")

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
@click.option("--stack", help="path to the stack", required=False)
@click.option("--include", help="only build these containers")
@click.option("--exclude", help="don't build these containers")
@click.option("--git-ssh/--no-git-ssh", is_flag=True, default=get_config_setting("git-ssh", False), help="use SSH for git rather than HTTPS")
@click.option("--build-policy", default=BUILD_POLICIES[0], help=f"Available policies: {BUILD_POLICIES}")
@click.option("--extra-build-args", help="Supply extra arguments to build")
@click.option("--dont-pull-images", is_flag=True, default=False, help="Don't pull remote images (useful with k8s deployments).")
@click.option("--publish-images", is_flag=True, default=False, help="Publish the built images")
@click.option("--image-registry", help="Specify the remote image registry (default: auto-detect per-container)", default=get_config_setting("image-registry"))
@click.option("--target-arch", help="Specify a target architecture (only for use with --dont-pull-images)")
@click.pass_context
def command(ctx, stack, include, exclude, git_ssh, build_policy, extra_build_args, dont_pull_images, publish_images, image_registry, target_arch):
    """build stack containers"""
    if not stack:
        stack = ctx.obj.stack_path

    stack = resolve_stack(stack)
    build_containers(stack,
                     build_policy,
                     image_registry,
                     publish_images,
                     include,
                     exclude,
                     extra_build_args,
                     git_ssh,
                     target_arch,
                     dont_pull_images)
