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

# TODO: display the available list of containers; allow re-build of either all or specific containers

import os
import sys

import git
from decouple import config
import subprocess
import click
from pathlib import Path

from python_on_whales import DockerClient
from stack.opts import opts
from stack.util import include_exclude_check, stack_is_external, error_exit
from stack.base import get_npm_registry_url
from stack.build.build_types import BuildContext
from stack.build.publish import publish_image
from stack.build.build_util import get_containers_in_scope

from stack.util import get_dev_root_path

from stack.repos.setup_repositories import fs_path_for_repo

from stack.constants import container_file_name

from stack.build.build_util import StackContainer

from stack.repos.setup_repositories import host_and_path_for_repo

docker = DockerClient()

def container_exists_locally(tag):
    return docker.image.exists(tag)

def container_exists_remotely(tag):
    try:
        result = docker.manifest.inspect(tag)
        return True if result else False
    except:
        return False


# TODO: find a place for this
#    epilog="Config provided either in .env or settings.ini or env vars: BPI_REPO_BASE_DIR (defaults to ~/bpi)"


def make_container_build_env(dev_root_path: str,
                             container_build_dir: str,
                             debug: bool,
                             force_rebuild: bool,
                             extra_build_args: str):
    container_build_env = {
        "BPI_NPM_REGISTRY_URL": get_npm_registry_url(),
        "BPI_GO_AUTH_TOKEN": config("BPI_GO_AUTH_TOKEN", default=""),
        "BPI_NPM_AUTH_TOKEN": config("BPI_NPM_AUTH_TOKEN", default=""),
        "BPI_REPO_BASE_DIR": dev_root_path,
        "BPI_CONTAINER_BASE_DIR": container_build_dir,
        "BPI_HOST_UID": f"{os.getuid()}",
        "BPI_HOST_GID": f"{os.getgid()}",
        "DOCKER_BUILDKIT": config("DOCKER_BUILDKIT", default="0")
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
        print(f"Building: {build_context.container}")

    default_container_tag = f"{build_context.container}:stack"
    build_context.container_build_env.update({"BPI_DEFAULT_CONTAINER_IMAGE_TAG": default_container_tag})

    # Check if this is in an external stack
    if stack_is_external(build_context.stack):
        container_parent_dir = Path(build_context.stack).parent.parent.joinpath("container-build")
        temp_build_dir = container_parent_dir.joinpath(build_context.container.replace("/", "-"))
        temp_build_script_filename = temp_build_dir.joinpath("build.sh")
        # Now check if the container exists in the external stack.
        if not temp_build_script_filename.exists():
            # If not, revert to building an internal container
            container_parent_dir = build_context.container_build_dir
    else:
        container_parent_dir = build_context.container_build_dir

    build_dir = container_parent_dir.joinpath(build_context.container.replace("/", "-"))
    build_script_filename = build_dir.joinpath("build.sh")

    if opts.o.verbose:
        print(f"Build script filename: {build_script_filename}")
    if os.path.exists(build_script_filename):
        build_command = build_script_filename.as_posix()
    else:
        if opts.o.verbose:
            print(f"No script file found: {build_script_filename}, using default build script")
        repo_dir = build_context.container.split('/')[1]
        # TODO: make this less of a hack -- should be specified in some metadata somewhere
        # Check if we have a repo for this container. If not, set the context dir to the container-build subdir
        repo_full_path = os.path.join(build_context.dev_root_path, repo_dir)
        repo_dir_or_build_dir = repo_full_path if os.path.exists(repo_full_path) else build_dir
        build_command = os.path.join(build_context.container_build_dir,
                                     "default-build.sh") + f" {default_container_tag} {repo_dir_or_build_dir}"
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


@click.command()
@click.option('--include', help="only build these containers")
@click.option('--exclude', help="don't build these containers")
@click.option("--force-rebuild", is_flag=True, default=False, help="Override dependency checking -- always rebuild")
@click.option("--extra-build-args", help="Supply extra arguments to build")
@click.option("--publish-images", is_flag=True, default=False, help="Publish the built images in the specified image registry")
@click.option("--image-registry", help="Specify the image registry for --publish-images")
@click.pass_context
def command(ctx, include, exclude, force_rebuild, extra_build_args, publish_images, image_registry):
    '''build the set of containers required for a complete stack'''

    stack = ctx.obj.stack

    # See: https://stackoverflow.com/questions/25389095/python-get-path-of-root-project-structure
    container_build_dir = Path(__file__).absolute().parent.parent.joinpath("data", "container-build")

    dev_root_path = get_dev_root_path(ctx)

    if not opts.o.quiet:
        print(f'Dev Root is: {dev_root_path}')

    if not os.path.isdir(dev_root_path):
        print('Dev root directory doesn\'t exist, creating')

    if publish_images:
        if not image_registry:
            error_exit("--image-registry must be supplied with --publish-images")

    container_build_env = make_container_build_env(dev_root_path,
                                                   container_build_dir,
                                                   opts.o.debug,
                                                   force_rebuild,
                                                   extra_build_args)

    # check if we have any repos that specify the container targets / build info
    containers_in_scope = [c for c in get_containers_in_scope(stack) if include_exclude_check(c, include, exclude)]
    for container in containers_in_scope:
        if not include_exclude_check(container.name, include, exclude):
            print(f"Skipping container {container.name}, it was excluded.")
            continue

        container_needs_built = True
        container_needs_pulled = False

        if container.ref:
            fs_path_for_container_specs = fs_path_for_repo(container.ref, dev_root_path)
            if not os.path.exists(fs_path_for_container_specs):
                print(f"Error: Missing container repo for {fs_path_for_container_specs}, run setup-repositories")
                sys.exit(1)

            container_spec_yml_path = os.path.join(fs_path_for_container_specs, container_file_name)
            if container.path:
                container_spec_yml_path = os.path.join(fs_path_for_container_specs, container.path, container_file_name)

            container_spec = StackContainer().init_from_file(container_spec_yml_path)
            if container_spec.ref:
                target_hash = None
                repo_host, repo_path, branch_or_hash_from_spec = host_and_path_for_repo(container_spec.ref)
                target_fs_repo_path = fs_path_for_repo(container_spec.ref, dev_root_path)
                # does the ref include a hash?
                if branch_or_hash_from_spec and len(branch_or_hash_from_spec) == 40 and all(c in string.hexdigits for c in branch_or_hash_from_spec):
                    target_hash = branch_or_hash_from_spec
                else:
                    git_client = git.cmd.Git()
                    # How to handle a mix of https and ssh?
                    print(branch_or_hash_from_spec)
                    result = git_client.ls_remote(f"https://{repo_host}/{repo_path}", branch_or_hash_from_spec)
                    if result:
                        target_hash = result.split()[0]

                container_tag = f"{container_spec.name}:{target_hash}"[:128]
                if container_exists_locally(container_tag):
                    print(f"Container {container_tag} exists locally.")
                    container_needs_pulled = False
                    container_needs_built = False
                elif container_exists_remotely(container_tag):
                    print(f"Container {container_tag} exists remotely.")
                    container_needs_pulled = True
                    container_needs_built = False
                else:
                    container_needs_pulled = False
                    container_needs_built = True
                    if not os.path.exists(target_fs_repo_path):
                        print("Git clone...")


        if container_needs_pulled:
            docker.image.pull(container_tag)
            docker.image.tag(container_tag, f"{container_spec.name}:stack")
        elif container_needs_built:
            build_context = BuildContext(
                stack,
                container,
                container_build_dir,
                container_build_env,
                dev_root_path
            )
            result = process_container(build_context)
            if result:
                if publish_images:
                    publish_image(f"{container}:stack", image_registry)
            else:
                print(f"Error running build for {build_context.container}")
                if not opts.o.continue_on_error:
                    error_exit("container build failed and --continue-on-error not set, exiting")
                    sys.exit(1)
                else:
                    print("****** Container Build Error, continuing because --continue-on-error is set")
