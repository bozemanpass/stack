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
import os
import sys

from stack.cli_util import StackCLI, load_subcommands_from_stack
from stack.command_types import CommandOptions
from stack.repos import fetch
from stack.repos import setup_repositories
from stack.build import prepare_containers
from stack.deploy import deploy
from stack import version
from stack.deploy import deployment
from stack import opts
from stack import update
from stack.webapp import webapp
from stack.util import stack_is_external, error_exit

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])

STACK_USE_BUILTIN_STACK = "true" == os.environ.get("STACK_USE_BUILTIN_STACK", "false")


@click.group(context_settings=CONTEXT_SETTINGS, cls=StackCLI)
@click.option("--stack", help="path to the stack to build/deploy")
@click.option("--verbose", help="more detailed output", is_flag=True, default=False)
@click.option("--debug", help="enable debug logging", is_flag=True, default=False)
# TEL: Hide these for now, until we make sure they are consistently implemented.
@click.option("--quiet", is_flag=True, default=False, hidden=True)
@click.option("--dry-run", is_flag=True, default=False, hidden=True)
@click.option("--continue-on-error", is_flag=True, default=False, hidden=True)
@click.pass_context
def cli(ctx, stack, quiet, verbose, dry_run, debug, continue_on_error):
    """BPI stack"""
    if stack and not stack_is_external(stack) and not STACK_USE_BUILTIN_STACK:
        error_exit(f"Stack {stack} does not exist")

    command_options = CommandOptions(stack, quiet, verbose, dry_run, debug, continue_on_error)
    opts.opts.o = command_options
    ctx.obj = command_options


cli.add_command(deploy.command, "deploy")
cli.add_command(deployment.command, "deployment")
cli.add_command(fetch.command, "fetch")
cli.add_command(prepare_containers.command, "prepare-containers")
cli.add_command(update.command, "update")
cli.add_command(version.command, "version")
cli.add_command(webapp.command, "webapp")

# Hidden commands
cli.add_command(prepare_containers.legacy_command, "build-containers")
cli.add_command(setup_repositories.legacy_command, "fetch repositories")

# We only try to load external commands from an external stack.
if not STACK_USE_BUILTIN_STACK:
    stack_path = None
    for i in range(len(sys.argv)):
        arg = sys.argv[i]
        if arg == "--stack":
            if i + 1 < len(sys.argv):
                stack_path = sys.argv[i + 1]
                break
    if stack_path:
        load_subcommands_from_stack(cli, stack_path)
