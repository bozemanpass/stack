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
# BPI_REPO_BASE_DIR defaults to ~/bpi


import click

from git import exc

from stack.build.build_util import host_and_path_for_repo
from stack.config.util import get_config_setting
from stack.opts import opts
from stack.repos.setup_repositories import process_repo
from stack.util import error_exit, get_dev_root_path


@click.command()
@click.argument("stack-locator")
@click.option("--git-ssh", is_flag=True, default=get_config_setting("git-ssh", False), help="use SSH for git rather than HTTPS")
@click.option("--check-only", is_flag=True, default=False, help="just check that the repo is available")
@click.option("--pull", is_flag=True, default=False, help="pull the latest changes for an existing stack")
@click.pass_context
def command(ctx, stack_locator, git_ssh, check_only, pull):
    """clone a stack repository"""
    dev_root_path = get_dev_root_path(ctx)
    if not opts.o.quiet:
        print(f"Dev Root is: {dev_root_path}")

    try:
        _, _, _ = host_and_path_for_repo(stack_locator)
    except:  # noqa: E722
        error_exit(f"{stack_locator} is not a valid stack locator")

    try:
        process_repo(pull, check_only, git_ssh, dev_root_path, None, stack_locator)
    except exc.GitCommandError as error:
        error_exit(f"\n******* git command returned error exit status:\n{error}")
