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

from stack.build.build_webapp import command as build_webapp
from stack.build.wrappers import get_available_wrappers
from stack.deploy.webapp.deploy_webapp import create as deploy_webapp
from stack.deploy.webapp.run_webapp import command as run_webapp
from stack.log import output_main


@click.group()
@click.pass_context
def command(ctx):
    """build, run, and deploy webapps"""
    pass


@click.command()
@click.pass_context
def list_wrappers(ctx):
    """list the available container wrapper schemes"""
    for wrapper in get_available_wrappers():
        source = "builtin" if wrapper.is_builtin() else str(wrapper.dir)
        output_main(f"{wrapper.name.ljust(16)} {wrapper.base_container.ljust(36)} {source.ljust(24)} {wrapper.description}")


command.add_command(build_webapp, "build")
command.add_command(deploy_webapp, "deploy")
command.add_command(run_webapp, "run")
command.add_command(list_wrappers, "wrappers")
