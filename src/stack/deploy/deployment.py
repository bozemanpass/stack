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

import click
from pathlib import Path
import sys
from stack import constants
from stack.deploy.images import push_images_operation
from stack.deploy.deploy import (
    up_operation,
    down_operation,
    ps_operation,
    port_operation,
    status_operation,
)
from stack.deploy.deploy import (
    exec_operation,
    logs_operation,
    create_deploy_context,
    update_operation,
)
from stack.deploy.deploy_types import DeployCommandContext
from stack.deploy.deployment_context import DeploymentContext


@click.group()
@click.option("--dir", required=True, help="path to deployment directory")
@click.pass_context
def command(ctx, dir):
    """manage a deployed stack (start, stop, etc.)"""

    # Check dir is valid
    dir_path = Path(dir)
    if not dir_path.exists():
        print(f"Error: deployment directory {dir} does not exist")
        sys.exit(1)
    if not dir_path.is_dir():
        print(f"Error: supplied deployment directory path {dir} exists but is a file not a directory")
        sys.exit(1)
    # Store the deployment context for subcommands
    deployment_context = DeploymentContext()
    deployment_context.init(dir_path)
    ctx.obj = deployment_context


def make_deploy_context(ctx) -> DeployCommandContext:
    context: DeploymentContext = ctx.obj
    env_file = context.get_env_file()
    cluster_name = context.get_cluster_id()
    if constants.deploy_to_key in context.spec.obj:
        deployment_type = context.spec.obj[constants.deploy_to_key]
    else:
        deployment_type = constants.compose_deploy_type
    stack = context.deployment_dir
    return create_deploy_context(
        ctx.parent.parent.obj,
        context,
        stack,
        None,
        None,
        cluster_name,
        env_file,
        deployment_type,
    )


@command.command()
@click.option(
    "--stay-attached/--detatch-terminal",
    default=False,
    help="detatch or not to see container stdout",
)
@click.option(
    "--skip-cluster-management/--perform-cluster-management",
    default=False,
    help="Skip cluster initialization/tear-down (only for kind-k8s deployments)",
)
@click.argument("extra_args", nargs=-1)  # help: command: start <service1> <service2>
@click.pass_context
def start(ctx, stay_attached, skip_cluster_management, extra_args):
    """start the stack"""
    ctx.obj = make_deploy_context(ctx)
    services_list = list(extra_args) or None
    up_operation(ctx, services_list, stay_attached, skip_cluster_management)


@command.command()
@click.option("--delete-volumes/--preserve-volumes", default=False, help="delete data volumes")
@click.option(
    "--skip-cluster-management/--perform-cluster-management",
    default=False,
    help="Skip cluster initialization/tear-down (only for kind-k8s deployments)",
)
@click.argument("extra_args", nargs=-1)  # help: command: down <service1> <service2>
@click.pass_context
def stop(ctx, delete_volumes, skip_cluster_management, extra_args):
    """stop the stack and remove the containers"""
    # TODO: add cluster name and env file here
    ctx.obj = make_deploy_context(ctx)
    down_operation(ctx, delete_volumes, extra_args, skip_cluster_management)


@command.command()
@click.pass_context
def ps(ctx):
    """list running containers in the stack"""
    ctx.obj = make_deploy_context(ctx)
    ps_operation(ctx)


@command.command()
@click.pass_context
def push_images(ctx):
    """push container images/tags to the image registry"""
    deploy_command_context: DeployCommandContext = make_deploy_context(ctx)
    deployment_context: DeploymentContext = ctx.obj
    push_images_operation(deploy_command_context, deployment_context)


@command.command()
@click.argument("extra_args", nargs=-1)  # help: command: port <service1> <service2>
@click.pass_context
def port(ctx, extra_args):
    """list mapped ports"""
    ctx.obj = make_deploy_context(ctx)
    port_operation(ctx, extra_args)


@command.command()
@click.argument("extra_args", nargs=-1)  # help: command: exec <service> <command>
@click.pass_context
def exec(ctx, extra_args):
    """execute a command inside a container"""
    ctx.obj = make_deploy_context(ctx)
    exec_operation(ctx, extra_args)


@command.command()
@click.option("--tail", "-n", default=None, help="number of lines to display")
@click.option("--follow", "-f", is_flag=True, default=False, help="follow log output")
@click.argument("extra_args", nargs=-1)  # help: command: logs <service1> <service2>
@click.pass_context
def logs(ctx, tail, follow, extra_args):
    """get logs for running containers"""
    ctx.obj = make_deploy_context(ctx)
    logs_operation(ctx, tail, follow, extra_args)


@command.command()
@click.pass_context
def status(ctx):
    """report stack and container status"""
    ctx.obj = make_deploy_context(ctx)
    status_operation(ctx)


@command.command()
@click.pass_context
def update(ctx):
    """trigger an update of the deployed stack"""
    ctx.obj = make_deploy_context(ctx)
    update_operation(ctx)
