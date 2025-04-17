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
from stack.deploy.webapp.deploy_webapp import command as deploy_webapp
from stack.deploy.webapp.run_webapp import command as run_webapp


@click.group()
@click.pass_context
def command(ctx):
    '''build, run, and deploy webapps'''
    pass


command.add_command(build_webapp, "build")
command.add_command(deploy_webapp, "deploy")
command.add_command(run_webapp, "run")
