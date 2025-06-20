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
import os
import git


from stack import constants
from stack.build.build_util import get_containers_in_scope
from stack.config.util import get_config_setting, get_dev_root_path
from stack.deploy.stack import get_parsed_stack_config, resolve_stack
from stack.opts import opts
from stack.repos.repo_util import process_repo, parse_branches, branch_strip
from stack.util import (
    include_exclude_check,
    error_exit,
)


@click.command()
@click.option("--stack", help="path to the stack", required=False)
@click.option("--include", help="only clone these repositories")
@click.option("--exclude", help="don't clone these repositories")
@click.option("--git-ssh", is_flag=True, default=get_config_setting("git-ssh", False), help="use SSH for git rather than HTTPS")
@click.option("--check-only", is_flag=True, default=False, help="just check that the repo is available")
@click.option("--pull", is_flag=True, default=False, help="pull the latest changes for an existing stack")
@click.option("--branches", help="override branches for repositories")
@click.pass_context
def command(ctx, stack, include, exclude, git_ssh, check_only, pull, branches):
    """clone the repositories needed by the stack"""
    quiet = opts.o.quiet
    verbose = opts.o.verbose

    if not stack:
        stack = ctx.obj.stack_path

    top_stack = resolve_stack(stack)
    required_stacks = []
    if top_stack.is_super_stack():
        for stack_refs in top_stack.get_required_stacks():
            try:
                repo_path = process_repo(pull, check_only, git_ssh, get_dev_root_path(), None, stack_refs[constants.ref_key])
            except git.exc.GitCommandError as error:
                error_exit(f"\n******* git command returned error exit status:\n{error}")
            required_stacks.append(repo_path.joinpath(stack_refs[constants.path_key]))
    else:
        required_stacks.append(top_stack)

    for stack in required_stacks:
        stack = get_parsed_stack_config(stack)
        branches_array = []

        if branches:
            branches_array = parse_branches(branches)

        if branches_array and verbose:
            print(f"Branches are: {branches_array}")

        dev_root_path = get_dev_root_path()

        if verbose:
            print(f"Dev Root is: {dev_root_path}")

        if not os.path.isdir(dev_root_path):
            if not quiet:
                print("Dev root directory doesn't exist, creating")
            os.makedirs(dev_root_path)

        repos_in_scope = stack.get("repos", [])

        # containers can reference an external repo
        containers_in_scope = get_containers_in_scope(stack)
        for c in containers_in_scope:
            if c.ref and c.ref not in repos_in_scope:
                repos_in_scope.append(c.ref)

        if verbose:
            print(f"Repos: {repos_in_scope}")
            if stack:
                print(f"Stack: {stack.name}")

        if not repos_in_scope:
            if not opts.o.quiet:
                print(f"NOTE: stack {stack.name} does not define any repositories")
            continue

        repos = []
        for repo in repos_in_scope:
            if include_exclude_check(branch_strip(repo), include, exclude):
                repos.append(repo)
            else:
                if verbose:
                    print(f"Excluding: {repo}")

        for repo in repos:
            try:
                process_repo(pull, check_only, git_ssh, dev_root_path, branches_array, repo)
            except git.exc.GitCommandError as error:
                error_exit(f"\n******* git command returned error exit status:\n{error}")
