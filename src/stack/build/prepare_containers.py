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
# BPI_REPO_BASE_DIR defaults to ~/bpi

import click
import git
import os
import subprocess
import sys

from decouple import config
from pathlib import Path
from python_on_whales import DockerClient

from stack.base import get_npm_registry_url
from stack.build.build_types import BuildContext
from stack.build.build_util import ContainerSpec, get_containers_in_scope, container_exists_locally, container_exists_remotely, local_container_arch, host_and_path_for_repo, image_registry_for_repo
from stack.build.publish import publish_image
from stack.constants import container_file_name, container_lock_file_name
from stack.opts import opts
from stack.repos.setup_repositories import fs_path_for_repo, process_repo
from stack.util import get_dev_root_path, include_exclude_check, stack_is_external, error_exit, get_yaml


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
#    epilog="Config provided either in .env or settings.ini or env vars: BPI_REPO_BASE_DIR (defaults to ~/bpi)"


def make_container_build_env(dev_root_path: str, container_build_dir: str, debug: bool, force_rebuild: bool, extra_build_args: str):
    container_build_env = {
        "BPI_NPM_REGISTRY_URL": get_npm_registry_url(),
        "BPI_GO_AUTH_TOKEN": config("BPI_GO_AUTH_TOKEN", default=""),
        "BPI_NPM_AUTH_TOKEN": config("BPI_NPM_AUTH_TOKEN", default=""),
        "BPI_REPO_BASE_DIR": dev_root_path,
        "BPI_CONTAINER_BASE_DIR": container_build_dir,
        "BPI_HOST_UID": f"{os.getuid()}",
        "BPI_HOST_GID": f"{os.getgid()}",
        "BPI_IMAGE_LOCAL_TAG": "stack",
        "DOCKER_BUILDKIT": config("DOCKER_BUILDKIT", default="0"),
    }
    container_build_env.update({"BPI_SCRIPT_DEBUG": "true"} if debug else {})
    container_build_env.update({"BPI_FORCE_REBUILD": "true"} if force_rebuild else {})
    container_build_env.update({"BPI_CONTAINER_EXTRA_BUILD_ARGS": extra_build_args} if extra_build_args else {})
    docker_host_env = os.getenv("DOCKER_HOST")
    if docker_host_env:
        container_build_env.update({"DOCKER_HOST": docker_host_env})

    return container_build_env


def process_container(build_context: BuildContext) -> bool:
    if not opts.o.quiet:
        print(f"Building: {build_context.container.name}:stack")

    default_container_tag = f"{build_context.container.name}:stack"
    build_context.container_build_env.update({"BPI_DEFAULT_CONTAINER_IMAGE_TAG": default_container_tag})

    build_dir = None
    build_script_filename = None

    # Check if this is in an external stack
    if stack_is_external(build_context.stack):
        if build_context.container.build:
            build_script_filename = Path(build_context.container.file_path).parent.joinpath(build_context.container.build)
            build_dir = build_script_filename.parent
        else:
            container_build_script_dir = Path(build_context.stack).parent.parent.joinpath("container-build")
            if os.path.exists(container_build_script_dir):
                temp_build_dir = container_build_script_dir.joinpath(build_context.container.name.replace("/", "-"))
                temp_build_script_filename = temp_build_dir.joinpath("build.sh")
                # Now check if the container exists in the external stack.
                if not temp_build_script_filename.exists():
                    # If not, revert to building an internal container
                    container_build_script_dir = build_context.container_build_dir
                build_dir = container_build_script_dir.joinpath(build_context.container.name.replace("/", "-"))
                build_script_filename = build_dir.joinpath("build.sh")
    if not build_dir:
        build_dir = build_context.container_build_dir.joinpath(build_context.container.name.replace("/", "-"))
        build_script_filename = build_dir.joinpath("build.sh")

    if opts.o.verbose:
        print(f"Build script filename: {build_script_filename}")
    if os.path.exists(build_script_filename):
        build_command = build_script_filename.as_posix()
    else:
        if opts.o.verbose:
            print(f"No script file found: {build_script_filename}, using default build script")
        repo_dir = build_context.container.ref.split("/")[1] if build_context.container.ref else build_context.container.name.split("/")[1]
        # TODO: make this less of a hack -- should be specified in some metadata somewhere
        # Check if we have a repo for this container. If not, set the context dir to the container-build subdir
        repo_full_path = os.path.join(build_context.dev_root_path, repo_dir)
        repo_dir_or_build_dir = repo_full_path if os.path.exists(repo_full_path) else build_dir
        build_command = (
            os.path.join(build_context.container_build_dir, "default-build.sh")
            + f" {default_container_tag} {repo_dir_or_build_dir}"
        )

    build_context.container_build_env["BPI_IMAGE_NAME"] = build_context.container.name
    if not opts.o.dry_run:
        # No PATH at all causes failures with podman.
        if "PATH" not in build_context.container_build_env:
            build_context.container_build_env["PATH"] = os.environ["PATH"]
        if opts.o.verbose:
            print(f"Executing: {build_command} with environment: {build_context.container_build_env}")
        build_result = subprocess.run(build_command, shell=True, env=build_context.container_build_env)
        if opts.o.verbose:
            print(f"Return code is: {build_result.returncode}")
        if build_result.returncode != 0:
            return False
        else:
            return True
    else:
        print("Skipped")
        return True


@click.command(hidden=True)
@click.option("--include", help="only build these containers")
@click.option("--exclude", help="don't build these containers")
@click.option("--force-rebuild", is_flag=True, default=False, help="Override dependency checking -- always rebuild")
@click.option("--extra-build-args", help="Supply extra arguments to build")
@click.option("--publish-images", is_flag=True, default=False, help="Publish the built images in the specified image registry")
@click.option("--image-registry", help="Specify the image registry for --publish-images")
@click.pass_context
def legacy_command(ctx, include, exclude, force_rebuild, extra_build_args, publish_images, image_registry):
    """build the set of containers required for a complete stack"""

    # Legacy support for build-containers command.

    build_policy = "build"
    if force_rebuild:
        build_policy = "build-force"

    _prepare_containers(ctx, include, exclude, False, build_policy, extra_build_args, True, publish_images, image_registry, None)


@click.command()
@click.option("--include", help="only build these containers")
@click.option("--exclude", help="don't build these containers")
@click.option("--git-ssh", is_flag=True, default=False)
@click.option("--build-policy", default=BUILD_POLICIES[0], help=f"Available policies: {BUILD_POLICIES}")
@click.option("--extra-build-args", help="Supply extra arguments to build")
@click.option("--no-pull", is_flag=True, default=False, help="Don't pull remote images (useful with k8s deployments).")
@click.option("--publish-images", is_flag=True, default=False, help="Publish the built images")
@click.option("--image-registry", help="Specify the remote image registry (default: auto-detect per-container)")
@click.option("--target-arch", help="Specify a target architecture (only for use with --no-pull)")
@click.pass_context
def command(ctx, include, exclude, git_ssh, build_policy, extra_build_args, no_pull, publish_images, image_registry, target_arch):
    """build (or fetch pre-built) stack containers"""

    _prepare_containers(ctx, include, exclude, git_ssh, build_policy, extra_build_args, no_pull, publish_images, image_registry, target_arch)


def _prepare_containers(ctx, include, exclude, git_ssh, build_policy, extra_build_args, no_pull, publish_images, image_registry, target_arch):
    stack = ctx.obj.stack

    if build_policy not in BUILD_POLICIES:
        error_exit(f"{build_policy} is not one of {BUILD_POLICIES}")

    # See: https://stackoverflow.com/questions/25389095/python-get-path-of-root-project-structure
    container_build_dir = Path(__file__).absolute().parent.parent.joinpath("data", "container-build")

    dev_root_path = get_dev_root_path(ctx)

    if not opts.o.quiet:
        print(f"Dev Root is: {dev_root_path}")

    if not os.path.isdir(dev_root_path):
        print("Dev root directory doesn't exist, creating")

    if target_arch and target_arch != local_container_arch():
        if not no_pull:
            error_exit("--target-arch requires --no-pull")
        if build_policy != "prebuilt-remote":
            error_exit("--target-arch requires --build-policy prebuilt-remote")


    container_build_env = make_container_build_env(
        dev_root_path, container_build_dir, opts.o.debug, "build-force" == build_policy, extra_build_args
    )

    # check if we have any repos that specify the container targets / build info
    containers_in_scope = [c for c in get_containers_in_scope(stack) if include_exclude_check(c, include, exclude)]
    for stack_container in containers_in_scope:
        if not include_exclude_check(stack_container.name, include, exclude):
            print(f"Skipping container {stack_container.name}, it was excluded.")
            continue

        container_needs_built = True
        container_was_built = False
        container_needs_pulled = False
        container_tag = None
        # TODO: Handle stack_container.path
        container_spec = ContainerSpec(stack_container.name, stack_container.ref)
        stack_local_tag = f"{container_spec.name}:stack"
        stack_legacy_tag = f"{container_spec.name}:local"
        image_registry_to_pull_this_container = image_registry
        image_registry_to_push_this_container = image_registry

        if stack_container.ref:
            fs_path_for_container_specs = fs_path_for_repo(stack_container.ref, dev_root_path)
            if not os.path.exists(fs_path_for_container_specs):
                print(f"Error: Missing container repo for {fs_path_for_container_specs}, run fetch repositories")
                sys.exit(1)

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
                                print(
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
                    print(f"Container {container_tag} exists locally.")
                    container_needs_pulled = False
                    container_needs_built = False
                    # Tag the local copy to point at it.
                    docker.image.tag(container_tag, stack_local_tag)
                else:
                    if build_policy in [ "as-needed", "prebuilt", "prebuilt-remote", ]:
                        exists_remotely, image_registry_to_pull_this_container = container_exists_remotely(container_tag, image_registries_to_check, target_arch)
                        if exists_remotely:
                            if image_registry_to_pull_this_container:
                                print(f"Container {image_registry_to_pull_this_container}:{container_tag} exists remotely.")
                            else:
                                print(f"Container {container_tag} exists remotely.")
                            container_needs_pulled = not no_pull
                            container_needs_built = False

                if container_needs_built:
                    if build_policy in ["prebuilt", "prebuilt-local", "prebuilt-remote"]:
                        error_exit(f"Container {container_tag} not available prebuilt.")
                    else:
                        print(f"Container {container_tag} needs to be built.")
                        container_needs_pulled = False
                        container_needs_built = True
                        if not os.path.exists(target_fs_repo_path):
                            reconstructed_ref = f"{container_spec.ref.split('@')[0]}@{target_hash}"
                            process_repo(False, False, git_ssh, dev_root_path, [], reconstructed_ref)
                        else:
                            print(
                                f"Building {container_tag} from {target_fs_repo_path}\n\t"
                                "IMPORTANT: source files may include changes or be on a different branch than specified in container.yml."
                            )

        if container_needs_pulled:
            if not container_tag:
                error_exit(f"Cannot pull container: tag missing.")
            # Pull the remote image
            if image_registry_to_pull_this_container:
                docker.image.pull(f"{image_registry_to_pull_this_container}/{container_tag}")
                # Tag the local copy to point at it.
                docker.image.tag(f"{image_registry_to_pull_this_container}/{container_tag}", container_tag)
            else:
                docker.image.pull(container_tag)
            # Tag the local copy to point at it.
            docker.image.tag(container_tag, stack_local_tag)
        elif container_needs_built:
            if build_policy in ["prebuilt", "prebuilt-local", "prebuilt-remote"]:
                error_exit(f"No prebuilt image available for: {container_spec.name}")
            build_context = BuildContext(stack, container_spec, container_build_dir, container_build_env, dev_root_path)

            for tag in [stack_legacy_tag, stack_local_tag, container_tag]:
                try:
                    docker.image.remove(tag)
                except:
                    pass

            result = process_container(build_context)
            if result:
                container_was_built = True
                # Handle legacy build scripts
                if container_exists_locally(stack_legacy_tag) and not container_exists_locally(stack_local_tag):
                    docker.image.tag(stack_legacy_tag, stack_local_tag)
            else:
                print(f"Error running build for {build_context.container}")
                if not opts.o.continue_on_error:
                    error_exit("container build failed and --continue-on-error not set, exiting")
                    sys.exit(1)
                else:
                    print("****** Container Build Error, continuing because --continue-on-error is set")

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
            publish_image(stack_local_tag, image_registry_to_push_this_container, container_version)
