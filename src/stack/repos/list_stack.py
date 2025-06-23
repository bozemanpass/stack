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

# env vars:
# STACK_REPO_BASE_DIR defaults to ~/bpi


import click

from stack.config.util import get_dev_root_path
from stack.opts import opts

from stack.deploy.stack import locate_stacks_beneath


@click.command()
@click.argument("filter", required=False)
@click.option("--show-path", is_flag=True, default=False, help="show stack path")
@click.pass_context
def command(ctx, filter, show_path):
    """list available stacks"""
    dev_root_path = get_dev_root_path()
    if opts.o.verbose:
        print(f"Dev Root is: {dev_root_path}")

    search_path = dev_root_path

    stacks = locate_stacks_beneath(search_path)
    stacks.sort(key=lambda s: s.name)

    if filter:
        stacks = [s for s in stacks if filter in str(s.file_path) or filter in s.name]

    max_name_len = 0
    max_path_len = 0
    for stack in stacks:
        max_name_len = max(max_name_len, len(stack.name))
        max_path_len = max(max_path_len, len(str(stack.file_path.parent)))

    padding = 8
    for stack in stacks:
        if show_path:
            print(f"{stack.name.ljust(max_name_len + padding)} {str(stack.file_path.parent).ljust(max_path_len + 8)}")
        else:
            print(stack.name)
