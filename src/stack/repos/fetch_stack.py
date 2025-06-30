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
# STACK_REPO_BASE_DIR defaults to ~/.stack/repos


import click

from git import exc

from stack.config.util import get_config_setting, get_dev_root_path, verbose_enabled
from stack.repos.repo_util import host_and_path_for_repo, process_repo
from stack.util import error_exit

from stack.log import log_debug


@click.command()
@click.argument("repo-locator")
@click.option(
    "--git-ssh/--no-git-ssh", is_flag=True, default=get_config_setting("git-ssh", False), help="use SSH for git rather than HTTPS"
)
@click.option("--git-pull", is_flag=True, default=False, help="pull the latest changes for an existing repo")
@click.pass_context
def command(ctx, repo_locator, git_ssh, git_pull):
    """clone a repository"""
    dev_root_path = get_dev_root_path()
    log_debug(f"Dev Root is: {dev_root_path}")

    try:
        _, _, _ = host_and_path_for_repo(repo_locator)
    except:  # noqa: E722
        error_exit(f"{repo_locator} is not a valid stack locator")

    try:
        process_repo(git_pull, False, git_ssh, dev_root_path, None, repo_locator)
    except exc.GitCommandError as error:
        error_exit(f"\n******* git command returned error exit status:\n{error}")
