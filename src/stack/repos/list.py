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

# env vars:
# STACK_REPO_BASE_DIR defaults to ~/bpi


import click

from stack.build.build_util import host_and_path_for_repo
from stack.config.util import get_config_setting, get_dev_root_path
from stack.deploy.stack import Stack
from stack.opts import opts
from stack.repos.setup_repositories import process_repo, fs_path_for_repo
from stack.util import error_exit


def locate_stacks_beneath(search_path):
    stacks = []
    if search_path.exists():
        for path in search_path.rglob('stack.yml'):
            stacks.append(Stack().init_from_file(path))

    return stacks


def locate_single_stack(search_path, stack_name):
    stacks = locate_stacks_beneath(search_path)
    candidates = [ s for s in stacks if s.name == stack_name ]
    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        error_exit(f"multiple stacks named {stack_name} found")
    return None


@click.command()
@click.argument("stack-locator", required=False)
@click.pass_context
def command(ctx, stack_locator):
    """list stacks in a repository"""
    dev_root_path = get_dev_root_path()
    if opts.o.verbose:
        print(f"Dev Root is: {dev_root_path}")

    search_path = dev_root_path

    stacks = locate_stacks_beneath(search_path)
    stacks.sort(key=lambda stack: stack.name)

    if stack_locator:
        stacks = [ s for s in stacks if stack_locator in str(s.file_path) or stack_locator in s.name ]

    max_name_len = 0
    max_path_len = 0
    for stack in stacks:
        max_name_len = max(max_name_len, len(stack.name))
        max_path_len = max(max_path_len, len(str(stack.file_path.parent)))

    padding = 8
    for stack in stacks:
        print(f"{stack.name.ljust(max_name_len + padding)} {str(stack.file_path.parent).ljust(max_path_len + 8)} {str(stack.repo_path)[len(str(dev_root_path))+1:]}")
