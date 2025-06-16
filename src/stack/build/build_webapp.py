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

# Builds webapp containers

# env vars:
# STACK_REPO_BASE_DIR defaults to ~/bpi

# TODO: display the available list of containers; allow re-build of either all or specific containers

import click
import os
import sys

from pathlib import Path

from stack.build import prepare_containers
from stack.build.build_types import BuildContext
from stack.build.build_util import ContainerSpec
from stack.deploy.stack import Stack
from stack.deploy.webapp.util import determine_base_container, TimedLogger
from stack.util import get_dev_root_path



@click.command()
@click.option('--base-container')
@click.option('--source-repo', help="directory containing the webapp to build", required=True)
@click.option("--force-rebuild", is_flag=True, default=False, help="Override dependency checking -- always rebuild")
@click.option("--extra-build-args", help="Supply extra arguments to build")
@click.option("--tag", help="Container tag (default: bpi/<app_name>:stack)")
@click.pass_context
def command(ctx, base_container, source_repo, force_rebuild, extra_build_args, tag):
    '''build the specified webapp container'''
    logger = TimedLogger()

    quiet = ctx.obj.quiet
    debug = ctx.obj.debug
    verbose = ctx.obj.verbose

    # See: https://stackoverflow.com/questions/25389095/python-get-path-of-root-project-structure
    container_build_dir = Path(__file__).absolute().parent.parent.joinpath("data", "container-build")

    dev_root_path = get_dev_root_path()

    if verbose:
        logger.log(f'Dev Root is: {dev_root_path}')

    if not base_container:
        base_container = determine_base_container(source_repo)

    # First build the base container.
    container_build_env = prepare_containers.make_container_build_env(dev_root_path, container_build_dir, debug,
                                                                    force_rebuild, extra_build_args)

    if verbose:
        logger.log(f"Building base container: {base_container}")

    build_context_1 = BuildContext(
        Stack(None),
        ContainerSpec(base_container),
        container_build_dir,
        container_build_env,
        dev_root_path,
    )
    ok = prepare_containers.process_container(build_context_1)
    if not ok:
        logger.log("ERROR: Build failed.")
        sys.exit(1)

    if verbose:
        logger.log(f"Base container {base_container} build finished.")

    # Now build the target webapp.  We use the same build script, but with a different Dockerfile and work dir.
    container_build_env["STACK_WEBAPP_BUILD_RUNNING"] = "true"
    container_build_env["STACK_CONTAINER_BUILD_WORK_DIR"] = os.path.abspath(source_repo)
    container_build_env["STACK_CONTAINER_BUILD_CONTAINERFILE"] = os.path.join(container_build_dir,
                                                                          base_container.replace("/", "-"),
                                                                          "Containerfile.webapp")
    if not tag:
        webapp_name = os.path.abspath(source_repo).split(os.path.sep)[-1]
        tag = f"bpi/{webapp_name}:stack"

    container_build_env["STACK_CONTAINER_BUILD_TAG"] = tag

    if verbose:
        logger.log(f"Building app container: {tag}")

    build_context_2 = BuildContext(
        Stack(None),
        ContainerSpec(base_container),
        container_build_dir,
        container_build_env,
        dev_root_path,
    )
    ok = prepare_containers.process_container(build_context_2)
    if not ok:
        logger.log("ERROR: Build failed.")
        sys.exit(1)

    if verbose:
        logger.log(f"App container {base_container} build finished.")
        logger.log("webapp build complete", show_step_time=False, show_total_time=True)
