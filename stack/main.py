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
import sys

from stack.cli_util import StackCLI, load_subcommands_from_stack
from stack.command_types import CommandOptions
from stack.repos import setup_repositories
from stack.repos import fetch_stack
from stack.build import build_containers, fetch_containers
from stack.build import build_npms
from stack.build import build_webapp
from stack.deploy.webapp import run_webapp, deploy_webapp
from stack.deploy import deploy
from stack import version
from stack.deploy import deployment
from stack import opts
from stack import update
from stack.util import stack_is_external, error_exit

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS, cls=StackCLI)
@click.option("--stack", help="path to the stack to build/deploy")
@click.option("--use-builtin-stack", is_flag=True, help="the stack is internal", hidden=True)
@click.option("--quiet", is_flag=True, default=False)
@click.option("--verbose", is_flag=True, default=False)
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--debug", is_flag=True, default=False)
@click.option("--continue-on-error", is_flag=True, default=False)
@click.pass_context
def cli(ctx, stack, use_builtin_stack, quiet, verbose, dry_run, debug, continue_on_error):
    """BPI stack"""
    if stack and not stack_is_external(stack) and not use_builtin_stack:
        error_exit(f"Stack {stack} does not exist")

    command_options = CommandOptions(stack, quiet, verbose, dry_run, debug, continue_on_error)
    opts.opts.o = command_options
    ctx.obj = command_options


cli.add_command(fetch_stack.command, "fetch-stack")
cli.add_command(setup_repositories.command, "setup-repositories")
cli.add_command(build_containers.command, "build-containers")
cli.add_command(fetch_containers.command, "fetch-containers")
cli.add_command(build_npms.command, "build-npms")
cli.add_command(build_webapp.command, "build-webapp")
cli.add_command(run_webapp.command, "run-webapp")
cli.add_command(deploy_webapp.command, "deploy-webapp")
cli.add_command(deploy.command, "deploy")
cli.add_command(deployment.command, "deployment")
cli.add_command(version.command, "version")
cli.add_command(update.command, "update")


# We only try to load external commands from an external stack.
if "--use-builtin-stack" not in sys.argv:
    stack_path = None
    for i in range(len(sys.argv)):
        arg = sys.argv[i]
        if arg == "--stack":
            stack_path = sys.argv[i + 1]
            break
    if stack_path:
        load_subcommands_from_stack(cli, stack_path)
