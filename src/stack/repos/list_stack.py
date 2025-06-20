# Copyright © 2022, 2023 Vulcanize
# Copyright © 2025 Bozeman Pass, Inc.
import os.path

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

from stack.config.util import get_dev_root_path, verbose_enabled
from stack.deploy.stack import Stack, get_parsed_stack_config
from stack.opts import opts
from stack.util import error_exit


def locate_stacks_beneath(search_path=get_dev_root_path()):
    stacks = []
    if search_path.exists():
        for path in search_path.rglob("stack.yml"):
            stacks.append(Stack().init_from_file(path))

    return stacks


def locate_single_stack(stack_name, search_path=get_dev_root_path()):
    stacks = locate_stacks_beneath(search_path)
    candidates = [s for s in stacks if s.name == stack_name]
    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        error_exit(f"multiple stacks named {stack_name} found")
    return None


def resolve_stack(stack_name):
    if stack_name.startswith("/") or (os.path.exists(stack_name) and os.path.isdir(stack_name)):
        stack = get_parsed_stack_config(stack_name)
        if verbose_enabled():
            print(f"Resolved {stack_name} to {stack.file_path.parent}")
    else:
        stack = locate_single_stack(stack_name)
        if verbose_enabled():
            print(f"Resolved {stack_name} to {stack.file_path.parent}")
    if not stack:
        error_exit(f"stack {stack_name} not found")
    return stack


@click.command()
@click.argument("stack-locator", required=False)
@click.option("--names-only", is_flag=True, default=False, help="only show stack names")
@click.option("--paths-only", is_flag=True, default=False, help="only show stack paths")
@click.pass_context
def command(ctx, stack_locator, names_only, paths_only):
    """list available stacks"""
    dev_root_path = get_dev_root_path()
    if opts.o.verbose:
        print(f"Dev Root is: {dev_root_path}")

    search_path = dev_root_path

    stacks = locate_stacks_beneath(search_path)
    stacks.sort(key=lambda s: s.name)

    if stack_locator:
        stacks = [s for s in stacks if stack_locator in str(s.file_path) or stack_locator in s.name]

    max_name_len = 0
    max_path_len = 0
    for stack in stacks:
        max_name_len = max(max_name_len, len(stack.name))
        max_path_len = max(max_path_len, len(str(stack.file_path.parent)))

    padding = 8
    for stack in stacks:
        if names_only:
            print(stack.name)
        elif paths_only:
            print(str(stack.file_path.parent))
        else:
            print(f"{stack.name.ljust(max_name_len + padding)} {str(stack.file_path.parent).ljust(max_path_len + 8)}")
