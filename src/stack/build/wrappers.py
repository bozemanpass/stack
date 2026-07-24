# Copyright © 2026 Bozeman Pass, Inc.

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

# Container "wrapper" schemes.
#
# A wrapper is a recipe for wrapping application source (e.g. a webapp or
# static content fetched from a git repository) in a container image, for
# applications that do not provide their own container build.  Each wrapper
# is described by a wrapper.yml manifest that lives alongside the build
# files for its base container image:
#
#   wrapper:
#     name: nextjs                          # short name, used to select the wrapper
#     description: Next.js webapp
#     base-container: bozemanpass/nextjs-base   # base image, built/pulled like any container
#     containerfile: Containerfile.webapp   # app-image build, context is the app source repo
#     port: 80                              # port the wrapped app serves on
#     default: true                         # optional: fallback when detection finds no match
#     detect:                               # optional: rules for auto-detection
#       package-json-dependency: next
#
# Wrappers are discovered from external repos fetched beneath the dev root
# (STACK_REPO_BASE_DIR), e.g. github.com/bozemanpass/stack-wrapper-webapp,
# and from the built-in container-build data directory.  An external wrapper
# with the same name as a built-in one takes precedence.

import json
import os

from pathlib import Path

from stack import constants
from stack.config.util import get_dev_root_path
from stack.util import get_yaml, error_exit


class Wrapper:
    name: str
    description: str
    base_container: str
    containerfile: str
    port: int
    default: bool
    detect: dict
    dir: Path

    def __init__(self):
        self.name = None
        self.description = None
        self.base_container = None
        self.containerfile = None
        self.port = None
        self.default = False
        self.detect = {}
        self.dir = None

    def __repr__(self):
        return str(self)

    def __str__(self):
        ret = {"name": self.name, "base-container": self.base_container, "dir": str(self.dir)}
        return json.dumps(ret)

    def init_from_file(self, file_path: Path):
        self.dir = Path(file_path).absolute().parent
        y = get_yaml().load(open(file_path, "r"))
        if "wrapper" not in y:
            error_exit(f"No 'wrapper' section in {file_path}.")
        wrapper_section = y["wrapper"]
        self.name = wrapper_section.get("name")
        if not self.name:
            error_exit(f"Missing required property 'name' in 'wrapper' section of {file_path}.")
        self.base_container = wrapper_section.get("base-container")
        if not self.base_container:
            error_exit(f"Missing required property 'base-container' in 'wrapper' section of {file_path}.")
        self.containerfile = wrapper_section.get("containerfile")
        if not self.containerfile:
            error_exit(f"Missing required property 'containerfile' in 'wrapper' section of {file_path}.")
        self.description = wrapper_section.get("description", "")
        self.port = wrapper_section.get("port")
        self.default = wrapper_section.get("default", False)
        self.detect = wrapper_section.get("detect", {})
        return self

    def containerfile_path(self) -> Path:
        return self.dir.joinpath(self.containerfile)

    def build_script_path(self) -> Path:
        return self.dir.joinpath("build.sh")

    def is_builtin(self) -> bool:
        return self.dir.is_relative_to(_builtin_container_build_dir())

    def matches(self, source_repo_dir) -> bool:
        if not self.detect:
            return False
        dependency = self.detect.get("package-json-dependency")
        if dependency:
            pkg_json_path = os.path.join(source_repo_dir, "package.json")
            if os.path.exists(pkg_json_path):
                pkg_json = json.load(open(pkg_json_path))
                if dependency in pkg_json.get("dependencies", {}):
                    return True
        return False


# Fetched automatically when no wrapper (or no matching wrapper) has been fetched yet.
DEFAULT_WRAPPER_REPOS = [
    "github.com/bozemanpass/stack-wrapper-webapp",
    "github.com/bozemanpass/stack-wrapper-static-content",
]


def _builtin_container_build_dir() -> Path:
    return Path(__file__).absolute().parent.parent.joinpath("data", "container-build")


def fetch_default_wrapper_repos(git_ssh=False):
    # Deferred import to avoid a circular dependency.
    from stack.repos.repo_util import process_repo

    for repo_ref in DEFAULT_WRAPPER_REPOS:
        process_repo(False, False, git_ssh, get_dev_root_path(), [], repo_ref)


def fetch_wrapper_repo(wrapper_ref: str, git_ssh=False) -> Path:
    # Fetch the wrapper repo (if not already present) and return its filesystem path.
    # Deferred import to avoid a circular dependency.
    from stack.repos.repo_util import fs_path_for_repo, process_repo

    repo_fs_path = fs_path_for_repo(wrapper_ref, get_dev_root_path())
    if not repo_fs_path:
        error_exit(f"Cannot parse wrapper repo ref: {wrapper_ref}")
    if not repo_fs_path.exists():
        process_repo(False, False, git_ssh, get_dev_root_path(), [], wrapper_ref)
    return repo_fs_path


def read_wrapper_locks(stack_dir: Path) -> dict:
    lock_file_path = Path(stack_dir).joinpath(constants.wrapper_lock_file_name)
    if lock_file_path.exists():
        return get_yaml().load(open(lock_file_path, "r")) or {}
    return {}


def write_wrapper_locks(stack_dir: Path, locks: dict):
    lock_file_path = Path(stack_dir).joinpath(constants.wrapper_lock_file_name)
    with open(lock_file_path, "w") as output_file:
        get_yaml().dump(locks, output_file)


def wrapper_repo_info(wrapper: Wrapper):
    """Return (repo_ref, current_hash, is_dirty) for the repo containing the wrapper.

    repo_ref is like github.com/org/repo, or None if it cannot be derived (e.g. the
    repo has a local-path remote)."""
    # Deferred import to avoid a circular dependency.
    from stack.repos.repo_util import find_repo_root, get_repo_current_hash, is_repo_dirty
    import git

    repo_root = find_repo_root(wrapper.dir)
    if not repo_root:
        return None, None, True

    repo_ref = None
    try:
        repo_url = git.Repo(repo_root).remotes[0].url
        if repo_url.startswith("https://") or repo_url.startswith("http://"):
            repo_url = repo_url.split("://", 2)[1]
            repo_host, repo_name = repo_url.split("/", 1)
        elif repo_url.startswith("git@"):
            repo_host, repo_name = repo_url.split(":", 1)
            repo_host = repo_host[4:]
        else:
            repo_host = None
        if repo_host:
            if repo_name.endswith(".git"):
                repo_name = repo_name[:-4]
            repo_ref = f"{repo_host}/{repo_name}"
    except (IndexError, git.exc.GitError):
        pass

    return repo_ref, get_repo_current_hash(repo_root), is_repo_dirty(repo_root)


def get_available_wrappers(search_root: Path = None):
    manifest_paths = []
    if search_root:
        # Restrict the search to a specific location (e.g. an explicitly referenced wrapper repo).
        if Path(search_root).exists():
            manifest_paths.extend(sorted(Path(search_root).rglob("wrapper.yml")))
    else:
        dev_root_path = get_dev_root_path()
        if dev_root_path and dev_root_path.exists():
            manifest_paths.extend(sorted(dev_root_path.rglob("wrapper.yml")))
        manifest_paths.extend(sorted(_builtin_container_build_dir().glob("*/wrapper.yml")))

    # External wrappers (earlier in the list) shadow built-in ones with the same name.
    wrappers = []
    seen_names = set()
    for manifest_path in manifest_paths:
        wrapper = Wrapper().init_from_file(manifest_path)
        if wrapper.name not in seen_names:
            seen_names.add(wrapper.name)
            wrappers.append(wrapper)
    return wrappers


def resolve_wrapper(name: str, search_root: Path = None):
    # Accept either the wrapper name or its base container name (for
    # backwards compatibility with --base-container).
    for wrapper in get_available_wrappers(search_root):
        if name in (wrapper.name, wrapper.base_container):
            return wrapper
    return None


def detect_wrapper(source_repo_dir):
    default_wrapper = None
    for wrapper in get_available_wrappers():
        if wrapper.default:
            default_wrapper = wrapper
        elif wrapper.matches(source_repo_dir):
            return wrapper
    return default_wrapper
