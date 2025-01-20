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

from stack.command_types import CommandOptions
from stack.repos import setup_repositories
from stack.repos import fetch_stack
from stack.build import build_containers, fetch_containers
from stack.build import build_npms
from stack.build import build_webapp
from stack.deploy.webapp import (run_webapp,
                                              deploy_webapp)
from stack.deploy import deploy
from stack import version
from stack.deploy import deployment
from stack import opts
from stack import update

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


@click.group(context_settings=CONTEXT_SETTINGS)
@click.option('--stack', help="specify a stack to build/deploy")
@click.option('--quiet', is_flag=True, default=False)
@click.option('--verbose', is_flag=True, default=False)
@click.option('--dry-run', is_flag=True, default=False)
@click.option('--local-stack', is_flag=True, default=False)
@click.option('--debug', is_flag=True, default=False)
@click.option('--continue-on-error', is_flag=True, default=False)
# See: https://click.palletsprojects.com/en/8.1.x/complex/#building-a-git-clone
@click.pass_context
def cli(ctx, stack, quiet, verbose, dry_run, local_stack, debug, continue_on_error):
    """BPI stack"""
    command_options = CommandOptions(stack, quiet, verbose, dry_run, local_stack, debug, continue_on_error)
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
cli.add_command(deploy.command, "deploy")  # deploy is an alias for deploy-system
cli.add_command(deploy.command, "deploy-system")
cli.add_command(deployment.command, "deployment")
cli.add_command(version.command, "version")
cli.add_command(update.command, "update")
