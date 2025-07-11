# Copyright © 2024 Vulcanize
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

import git
import hashlib
import os

from git.exc import GitCommandError
from pathlib import Path
from tqdm import tqdm

import stack.deploy.stack as stack_util

from stack import constants
from stack.build import build_util
from stack.config.util import get_dev_root_path
from stack.log import log_debug, log_info, get_log_file, is_info_enabled, log_is_console
from stack.opts import opts
from stack.util import include_exclude_check, error_exit


class GitProgress(git.RemoteProgress):
    def __init__(self):
        super().__init__()
        self.pbar = tqdm(unit="B", ascii=True, unit_scale=True, file=get_log_file())

    def update(self, op_code, cur_count, max_count=None, message=""):
        self.pbar.total = max_count
        self.pbar.n = cur_count
        self.pbar.refresh()


def branch_strip(s):
    return s.split("@")[0]


def host_and_path_for_repo(fully_qualified_repo):
    repo_branch_split = fully_qualified_repo.split("@")
    repo_branch = repo_branch_split[-1] if len(repo_branch_split) > 1 else None
    repo_host_split = repo_branch_split[0].split("/")
    # Legacy unqualified repo means github
    if len(repo_host_split) == 2:
        return "github.com", "/".join(repo_host_split), repo_branch
    else:
        if len(repo_host_split) == 3:
            # First part is the host
            return repo_host_split[0], "/".join(repo_host_split[1:]), repo_branch


def image_registry_for_repo(repository):
    host, path, _ = host_and_path_for_repo(repository)
    if "github.com" == host:
        return "ghcr.io"
    elif host:
        return host
    return None


def is_git_repo(path):
    try:
        _ = git.Repo(path).git_dir
        return True
    except:  # noqa: E722
        pass

    return False


def get_repo_current_hash(path):
    if not is_git_repo(path):
        return None

    return git.Repo(path).head.object.hexsha


def is_repo_dirty(path):
    if not is_git_repo(path):
        return None

    return git.Repo(path).is_dirty()


def hash_dirty_files(path):
    if not is_git_repo(path):
        return None

    if not is_repo_dirty(path):
        return ""

    m = hashlib.sha1()
    m.update(git.Repo(path).git.diff().encode())
    return m.hexdigest()


def find_repo_root(path):
    if isinstance(path, str):
        path = Path(path)

    ret = None
    path = path.absolute()
    while not ret and path and str(path.absolute().as_posix()) not in ["/"]:
        if is_git_repo(path):
            ret = path
        else:
            path = path.parent

    return ret


def get_container_tag_for_repo(path):
    tag = None
    git_hash = get_repo_current_hash(path)
    if git_hash:
        tag = git_hash
        if is_repo_dirty(path):
            dirty_hash = hash_dirty_files(path)
            tag = "stackdev-" + hashlib.sha1(f"{git_hash}:{dirty_hash}".encode()).hexdigest()
    return tag


# See: https://stackoverflow.com/questions/18659425/get-git-current-branch-tag-name
def _get_repo_current_branch_or_tag(full_filesystem_repo_path):
    current_repo_branch_or_tag = "***UNDETERMINED***"
    is_branch = False
    try:
        current_repo_branch_or_tag = git.Repo(full_filesystem_repo_path).active_branch.name
        is_branch = True
    except TypeError:
        # This means that the current ref is not a branch, so possibly a tag
        # Let's try to get the tag
        try:
            current_repo_branch_or_tag = git.Repo(full_filesystem_repo_path).git.describe("--tags", "--exact-match")
            # Note that git is asymmetric -- the tag you told it to check out may not be the one
            # you get back here (if there are multiple tags associated with the same commit)
        except GitCommandError:
            # If there is no matching branch or tag checked out, just use the current SHA
            current_repo_branch_or_tag = git.Repo(full_filesystem_repo_path).commit("HEAD").hexsha
    return current_repo_branch_or_tag, is_branch


def fs_path_for_repo(fully_qualified_repo, dev_root_path=get_dev_root_path()):
    repo_host, repo_path, repo_branch = host_and_path_for_repo(fully_qualified_repo)
    return Path(os.path.join(dev_root_path, repo_host, repo_path))


# TODO: fix the messy arg list here
def process_repo(pull, check_only, git_ssh, dev_root_path, branches_array, fully_qualified_repo):
    log_debug(f"Processing repo: {fully_qualified_repo}")
    repo_host, repo_path, repo_branch = host_and_path_for_repo(fully_qualified_repo)
    git_ssh_prefix = f"git@{repo_host}:"
    git_http_prefix = f"https://{repo_host}/"
    full_github_repo_path = f"{git_ssh_prefix if git_ssh else git_http_prefix}{repo_path}"
    full_filesystem_repo_path = Path(os.path.join(dev_root_path, repo_host, repo_path))
    full_filesystem_repo_path.parent.mkdir(parents=True, exist_ok=True)
    is_present = os.path.isdir(full_filesystem_repo_path)
    (current_repo_branch_or_tag, is_branch) = (
        _get_repo_current_branch_or_tag(full_filesystem_repo_path) if is_present else (None, None)
    )
    present_text = (
        f"already exists active {'branch' if is_branch else 'ref'}: {current_repo_branch_or_tag}"
        if is_present
        else "Needs to be fetched"
    )
    log_debug(f"Checking: {full_filesystem_repo_path}: {present_text}")
    # Quick check that it's actually a repo
    if is_present:
        if not is_git_repo(full_filesystem_repo_path):
            error_exit(f"{full_filesystem_repo_path} does not contain a valid git repository")
        else:
            if pull:
                log_debug(f"Running git pull for {full_filesystem_repo_path}")
                if not check_only:
                    if is_branch:
                        git_repo = git.Repo(full_filesystem_repo_path)
                        origin = git_repo.remotes.origin
                        origin.pull(progress=GitProgress() if log_is_console() and is_info_enabled() else None)
                    else:
                        log_info("skipping pull because this repo is not on a branch")
                else:
                    log_info("(git pull skipped)")
    if not is_present:
        # Clone
        log_debug(f"Running git clone for {full_github_repo_path} into {full_filesystem_repo_path}")
        if not opts.o.dry_run:
            git.Repo.clone_from(
                full_github_repo_path,
                full_filesystem_repo_path,
                progress=GitProgress() if log_is_console() and is_info_enabled() else None,
            )
        else:
            log_info("(git clone skipped)")
    # Checkout the requested branch, if one was specified
    branch_to_checkout = None
    if branches_array:
        # Find the current repo in the branches list
        log_info("Checking")
        for repo_branch in branches_array:
            repo_branch_tuple = repo_branch.split(" ")
            if repo_branch_tuple[0] == branch_strip(fully_qualified_repo):
                # checkout specified branch
                branch_to_checkout = repo_branch_tuple[1]
    else:
        branch_to_checkout = repo_branch

    if branch_to_checkout:
        if current_repo_branch_or_tag is None or (
            current_repo_branch_or_tag and (current_repo_branch_or_tag != branch_to_checkout)
        ):
            log_debug(f"switching to branch {branch_to_checkout} in repo {repo_path}")
            git_repo = git.Repo(full_filesystem_repo_path)
            # git checkout works for both branches and tags
            git_repo.git.checkout(branch_to_checkout)
        else:
            log_debug(f"repo {repo_path} is already on branch/tag {branch_to_checkout}")

    return full_filesystem_repo_path


def parse_branches(branches_string):
    if branches_string:
        result_array = []
        branches_directives = branches_string.split(",")
        for branch_directive in branches_directives:
            split_directive = branch_directive.split("@")
            if len(split_directive) != 2:
                error_exit(f"Error: branch specified is not valid: {branch_directive}")
            result_array.append(f"{split_directive[0]} {split_directive[1]}")
        return result_array
    else:
        return None


def clone_all_repos_for_stack(stack, include=None, exclude=None, pull=False, git_ssh=None):
    required_stacks = []
    if stack.is_super_stack():
        for stack_refs in stack.get_required_stacks():
            try:
                repo_path = process_repo(pull, False, git_ssh, get_dev_root_path(), None, stack_refs[constants.ref_key])
            except git.exc.GitCommandError as error:
                error_exit(f"\n******* git command returned error exit status:\n{error}")
            required_stacks.append(repo_path.joinpath(stack_refs[constants.path_key]))
    else:
        required_stacks.append(stack)

    for req_stack in required_stacks:
        req_stack = stack_util.get_parsed_stack_config(req_stack)

        dev_root_path = get_dev_root_path()
        log_debug(f"Dev Root is: {dev_root_path}")

        if not os.path.isdir(dev_root_path):
            log_debug("Dev root directory doesn't exist, creating")
            os.makedirs(dev_root_path)

        repos_in_scope = req_stack.get("repos", [])

        # containers can reference an external repo
        containers_in_scope = build_util.get_containers_in_scope(req_stack)
        for c in containers_in_scope:
            if c.ref and c.ref != "." and c.ref not in repos_in_scope:
                repos_in_scope.append(c.ref)

        log_debug(f"Repos: {repos_in_scope}")
        log_debug(f"Stack: {req_stack.name}")

        if not repos_in_scope:
            log_debug(f"NOTE: stack {req_stack.name} does not define any repositories")
            continue

        repos = []
        for repo in repos_in_scope:
            if include_exclude_check(branch_strip(repo), include, exclude):
                repos.append(repo)
            else:
                log_debug(f"Excluding: {repo}")

        for repo in repos:
            try:
                process_repo(pull, False, git_ssh, dev_root_path, None, repo)
            except git.exc.GitCommandError as error:
                error_exit(f"\n******* git command returned error exit status:\n{error}")
