# Copyright © 2022, 2023 Vulcanize
# Copyright © 2025 Bozeman Pass, Inc.
import os

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
from stack.repos import fetch
from stack.build import build
from stack.config import config
from stack.init import init
from stack.deploy import deployment_create
from stack import version
from stack.deploy import deployment
from stack import opts
from stack import update
from stack.webapp import webapp
from stack.util import STACK_USE_BUILTIN_STACK

from stack.src.stack.config.util import get_config_setting

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS, cls=StackCLI)
@click.option("--verbose", help="more detailed output", is_flag=True, default=get_config_setting("verbose", False))
@click.option("--debug", help="enable debug logging", is_flag=True, default=get_config_setting("debug", False))
@click.option("--stack", help="path to the stack")
@click.option(
    "--profile", help="name of the configuration profile to use", default=os.environ.get("STACK_CONFIG_PROFILE", "config")
)
# TEL: Hide these for now, until we make sure they are consistently implemented.
@click.option("--quiet", is_flag=True, default=False, hidden=True)
@click.option("--dry-run", is_flag=True, default=False, hidden=True)
@click.option("--continue-on-error", is_flag=True, default=False, hidden=True)
@click.pass_context
def cli(ctx, profile, quiet, verbose, dry_run, debug, continue_on_error, stack):
    """BPI stack"""
    command_options = CommandOptions(profile, stack, quiet, verbose, dry_run, debug, continue_on_error)
    opts.opts.o = command_options
    ctx.obj = command_options

    if command_options.profile:
        os.environ["STACK_CONFIG_PROFILE"] = command_options.profile
    if command_options.debug is not None:
        os.environ["STACK_DEBUG"] = command_options.debug
    if command_options.verbose is not None:
        os.environ["STACK_VERBOSE"] = command_options.verbose


cli.add_command(fetch.command, "fetch")
cli.add_command(build.command, "build")
cli.add_command(config.command, "config")
cli.add_command(deployment_create.create, "deploy")
cli.add_command(init.command, "init")
cli.add_command(deployment.command, "manage")
cli.add_command(update.command, "update")
cli.add_command(version.command, "version")
cli.add_command(webapp.command, "webapp")

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
