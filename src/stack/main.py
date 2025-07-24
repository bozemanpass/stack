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

from stack import opts
from stack import update
from stack import version

from stack.build import build, prepare
from stack.chart import chart
from stack.checklist import list_stack, checklist
from stack.cli_util import StackCLI, load_subcommands_from_stack
from stack.command_types import CommandOptions
from stack.complete import complete
from stack.config import config
from stack.config.util import get_config_setting
from stack.deploy import deployment
from stack.deploy import deployment_create
from stack.init import init
from stack.repos import fetch
from stack.util import STACK_USE_BUILTIN_STACK
from stack.webapp import webapp

from stack.log import LOG_LEVELS

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.group(context_settings=CONTEXT_SETTINGS, cls=StackCLI)
@click.option("--log-file", help="Log to file (default stdout/stderr)")
@click.option("--debug", help="enable debug options", is_flag=True, default=get_config_setting("debug", False))
@click.option("--stack", help="name or path of the stack")
@click.option(
    "--profile", help="name of the configuration profile to use", default=os.environ.get("STACK_CONFIG_PROFILE", "config")
)
# TEL: Hide these for now, until we make sure they are consistently implemented.
@click.option("--verbose", is_flag=True, default=False, help="Log extra details")
@click.option("--quiet", is_flag=True, default=False, help="Suppress unnecessary log output")
@click.option("--dry-run", is_flag=True, default=False, hidden=True)
@click.pass_context
def cli(ctx, profile, quiet, verbose, log_file, dry_run, debug, stack):
    """BPI stack"""

    if log_file:
        log_file = open(log_file, "w", encoding="utf-8")
    else:
        log_file = sys.stderr

    log_level = LOG_LEVELS["info"]
    if verbose:
        log_level = LOG_LEVELS["debug"]
    elif quiet:
        log_level = LOG_LEVELS["warn"]

    command_options = CommandOptions(profile, stack, log_level, log_file, dry_run, debug, quiet)
    opts.opts.o = command_options
    ctx.obj = command_options

    if command_options.profile:
        os.environ["STACK_CONFIG_PROFILE"] = command_options.profile
    if command_options.debug is not None:
        os.environ["STACK_DEBUG"] = str(command_options.debug)
    if command_options.log_level is not None:
        os.environ["STACK_LOG_LEVEL"] = str(command_options.log_level)


cli.add_command(build.command, "build")
cli.add_command(chart.command, "chart")
cli.add_command(checklist.command, "checklist")
cli.add_command(complete.command, "complete")
cli.add_command(config.command, "config")
cli.add_command(deployment_create.create, "deploy")
cli.add_command(fetch.command, "fetch")
cli.add_command(init.command, "init")
cli.add_command(list_stack.command, "list")
cli.add_command(deployment.command, "manage")
cli.add_command(prepare.command, "prepare")
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
