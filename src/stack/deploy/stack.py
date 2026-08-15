# Copyright © 2023 Vulcanize
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
import os
import typing

from pathlib import Path
from typing import Set, List

import stack.repos.repo_util as repo_util

from stack import constants
from stack.config.util import get_dev_root_path
from stack.log import log_debug, log_warn
from stack.util import get_yaml, get_stack_path, error_exit, resolve_compose_file, STACK_USE_BUILTIN_STACK


def _flatten_comment_tokens(entry):
    """Yield the CommentTokens in one ruamel comment-attachment entry.

    An entry is a token, a (possibly nested) list of tokens, or None, depending on
    where the comment sat; this flattens all of those shapes.
    """
    if entry is None:
        return
    if isinstance(entry, list):
        for item in entry:
            yield from _flatten_comment_tokens(item)
    else:
        yield entry


def _comment_tokens_in(node):
    """Yield every CommentToken attached anywhere within node's subtree."""
    ca = getattr(node, "ca", None)
    if ca is not None:
        yield from _flatten_comment_tokens(ca.comment)
        for entry in ca.items.values():
            yield from _flatten_comment_tokens(entry)
    if isinstance(node, dict):
        for value in node.values():
            yield from _comment_tokens_in(value)
    elif isinstance(node, list):
        for value in node:
            yield from _comment_tokens_in(value)


def _comment_lines(tokens):
    """Yield (column, text) for each non-empty comment line in the given tokens.

    A token can span several source lines (an end-of-line comment followed by
    full-line comments becomes one token).  The token's own column locates its
    first line; the later lines carry their leading whitespace in the value, which
    is their column.
    """
    for token in tokens:
        for i, raw in enumerate(token.value.splitlines()):
            text = raw.strip()
            if not text:
                continue
            column = token.start_mark.column if i == 0 else len(raw) - len(raw.lstrip())
            yield column, text


class Stack:
    name: str
    file_path: Path
    obj: typing.Any
    repo_path: Path

    def __init__(self, name: str = None) -> None:
        self.name = str(name)
        self.obj = {}
        self.file_path = None
        self.repo_path = None

    def __getitem__(self, item):
        return self.obj[item]

    def __setitem__(self, key, item):
        self.obj[key] = item

    def __contains__(self, item):
        return item in self.obj

    def is_super_stack(self):
        if self.get_required_stacks():
            return True
        return False

    def get(self, item, default=None):
        return self.obj.get(item, default)

    def init_from_file(self, file_path: Path):
        if isinstance(file_path, str):
            file_path = Path(file_path)
        self.obj = get_yaml().load(open(file_path, "rt"))
        self.name = self.obj.get("name", self.name)
        self.file_path = file_path.absolute()
        self._determine_repo_path()
        if self.get_repo_ref() and "pods" in self.obj:
            for pod in self.obj["pods"]:
                if type(pod) is not str:
                    # Inject the repo if possible
                    if "repository" not in pod:
                        pod["repository"] = self.get_repo_ref()
        return self

    def _determine_repo_path(self):
        if self.repo_path:
            return self.repo_path

        if self.file_path:
            check_path = self.file_path.parent.absolute()
        elif self.name:
            check_path = Path(self.name).absolute()
            if not check_path.exists():
                match = locate_single_stack(self.name, fail_on_multiple=False, fail_on_none=False)
                if match:
                    check_path = match.file_path.parent.absolute()
        else:
            check_path = None

        while not self.repo_path and check_path and str(check_path.absolute().as_posix()) not in ["/"]:
            if repo_util.is_git_repo(check_path):
                self.repo_path = check_path
            else:
                check_path = check_path.parent

        return self.repo_path

    def get_repo_ref(self):
        repo_url = self.get_repo_url()
        if not repo_url:
            return None

        if repo_url.startswith("https://") or repo_url.startswith("http://"):
            repo_url = repo_url.split("://", 2)[1]
            repo_host, repo_name = repo_url.split("/", 1)
        elif repo_url.startswith("git@"):
            repo_host, repo_name = repo_url.split(":", 1)
            repo_host = repo_host[4:]
        else:
            # Some other URL form (e.g. a local path) from which no ref can be derived.
            return None

        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        return f"{repo_host}/{repo_name}"

    def get_repo_name(self):
        ref = self.get_repo_ref()
        if ref:
            return ref.split("/", 1)[-1]
        return None

    def get_repo_url(self):
        if self._determine_repo_path():
            repo = git.Repo(self.repo_path)
            return repo.remotes[0].url
        return None

    def repo_is_local_checkout(self):
        """True when this stack was loaded from a checkout other than the dev-root clone
        of its repo -- a developer tree or a CI checkout.  Colocated containers of such a
        stack build directly from that checkout, and its repo is never cloned."""
        if not self._determine_repo_path():
            return False
        ref = self.get_repo_ref()
        if not ref:
            # No derivable repo ref (e.g. no usable remote): the checkout is all there is.
            return True
        dev_clone_path = repo_util.fs_path_for_repo(ref, get_dev_root_path())
        if not dev_clone_path:
            return True
        return Path(self.repo_path).resolve() != Path(dev_clone_path).resolve()

    def get_required_stacks(self):
        return self.get(constants.requires_key, {}).get(constants.stacks_key)

    def get_required_stacks_paths(self):
        if not self.is_super_stack():
            return [self.file_path.parent] if self.file_path else []

        ret = []
        for stack_refs in self.get_required_stacks():
            ret.append(determine_fs_path_for_stack(stack_refs[constants.ref_key], stack_refs[constants.path_key]))
        return ret

    def get_pods(self):
        return self.obj.get("pods", [])

    def get_pod_list(self):
        # Handle both old and new format
        pods = self.get_pods()
        if not pods:
            return []
        if type(pods[0]) is str:
            return pods
        return [p["name"] for p in pods]

    def load_pod_file(self, pod_name):
        pod_file_path = self.get_pod_file_path(pod_name)
        if pod_file_path:
            return get_yaml().load(open(pod_file_path, "rt"))
        return None

    def get_pod_file_path(self, pod_name):
        return get_pod_file_path(self, pod_name)

    def get_services(self):
        services = {}
        pods = self.get_pod_list()
        for pod in pods:
            parsed_pod_file = self.load_pod_file(pod)
            if constants.services_key in parsed_pod_file:
                for svc_name in parsed_pod_file[constants.services_key]:
                    services[svc_name] = parsed_pod_file[constants.services_key][svc_name]
        return services

    def get_ports(self):
        ports = {}
        pods = self.get_pod_list()
        for pod in pods:
            parsed_pod_file = self.load_pod_file(pod)
            if constants.services_key in parsed_pod_file:
                for svc_name, svc in parsed_pod_file[constants.services_key].items():
                    if constants.ports_key in svc:
                        # Ports can appear as strings or numbers.  We normalize them as strings.
                        ports[svc_name] = [str(x) for x in svc[constants.ports_key]]
        return ports

    def get_volumes(self):
        volumes = {}
        pods = self.get_pod_list()
        for pod in pods:
            parsed_pod_file = self.load_pod_file(pod)
            if constants.services_key in parsed_pod_file:
                for svc_name, svc in parsed_pod_file[constants.services_key].items():
                    if constants.volumes_key in svc:
                        volumes[svc_name] = svc[constants.volumes_key]
        return volumes

    def get_backup_targets(self):
        """Parse @stack backup-* annotations from the stack's composefiles.

        `backup-exclude` sits on a volume mount line, parsed the same way as the
        http-proxy port annotations (see get_http_proxy_targets).  `backup-command`
        and `backup-file-extension` are service-level: full-line comments written
        anywhere *inside* the service's block (see docs/backup.md).  Returns:

            {"exclude": [volume_name, ...],
             "commands": {service_name: {"command": str, "file-extension": str}}}
        """
        exclude = []
        commands = {}
        for pod in self.get_pod_list():
            parsed_pod_file = self.load_pod_file(pod)
            if constants.services_key not in parsed_pod_file:
                continue
            services = parsed_pod_file[constants.services_key]
            for svc_name, svc in services.items():
                if constants.volumes_key in svc:
                    volumes_section = svc[constants.volumes_key]
                    for i, mount in enumerate(volumes_section):
                        item_comments = volumes_section.ca.items.get(i)
                        if item_comments and item_comments[0]:
                            # Only the end-of-line comment (first line of the token) counts.
                            # ruamel attaches trailing block comments (e.g. a comment that heads
                            # the next service) to the preceding item; those must be ignored.
                            comment = item_comments[0].value.split("\n", 1)[0].strip()
                            if constants.stack_annotation_marker in comment \
                                    and constants.backup_exclude_annotation in comment:
                                exclude.append(str(mount).split(":")[0])
                self._parse_backup_command_annotations(services, svc_name, svc, commands)
        for svc_name in list(commands):
            if "command" not in commands[svc_name]:
                log_warn(
                    f"WARN: service '{svc_name}' has a {constants.backup_file_extension_annotation} "
                    f"annotation but no {constants.backup_command_annotation}; ignoring it"
                )
                del commands[svc_name]
        return {"exclude": exclude, "commands": commands}

    @staticmethod
    def _parse_backup_command_annotations(services, svc_name, svc, commands):
        """Collect this service's backup-command / backup-file-extension annotations.

        These are full-line comments written inside the service's block, so unlike the
        mount-line annotations there is no YAML item for them to be an end-of-line
        comment of: ruamel hangs them off whatever node precedes them, which varies
        with where in the block they are written.  So every comment attached within
        the service's subtree is scanned, line by line.

        A comment written at less indent than the service's keys is a heading for
        whatever comes next (typically the next service), which ruamel also attaches
        to the preceding node -- the same trap noted for the mount-line parse above.
        Those lines are rejected by their column, with a warning when one carries a
        backup annotation, since silently attaching it to the wrong service would be
        far worse than ignoring it.
        """
        # The column the service's keys start at; a genuinely in-block comment
        # cannot be left of it.
        svc_column = svc.lc.col if getattr(svc, "lc", None) else 0
        # Comments between the "name:" line and the first key attach to the services
        # map's entry for the name, not to the service itself, so both are scanned.
        tokens = list(_comment_tokens_in(svc)) + list(_flatten_comment_tokens(services.ca.items.get(svc_name)))
        for column, text in _comment_lines(tokens):
            if constants.stack_annotation_marker not in text:
                continue
            words = text.split()
            if constants.backup_command_annotation in words:
                annotation = constants.backup_command_annotation
            elif constants.backup_file_extension_annotation in words:
                annotation = constants.backup_file_extension_annotation
            else:
                continue
            if column < svc_column:
                log_warn(
                    f"WARN: ignoring {annotation} annotation not written inside a service block "
                    f"(after service '{svc_name}'): {text}"
                )
                continue
            value = text.split(annotation, 1)[1].strip()
            if not value:
                log_warn(f"WARN: ignoring empty {annotation} annotation on service '{svc_name}'")
                continue
            if annotation == constants.backup_command_annotation:
                commands.setdefault(svc_name, {})["command"] = value
            else:
                commands.setdefault(svc_name, {})["file-extension"] = value.split()[0]

    def get_http_proxy_targets(self, prefix=None):
        if prefix:
            if prefix == "/":
                prefix = None
            else:
                if not prefix.startswith("/"):
                    prefix = "/" + prefix
                prefix = prefix.rstrip("/")

        http_proxy_targets = []
        pods = self.get_pod_list()
        for pod in pods:
            parsed_pod_file = self.load_pod_file(pod)
            if constants.services_key in parsed_pod_file:
                for svc_name, svc in parsed_pod_file[constants.services_key].items():
                    if constants.ports_key in svc:
                        ports_section = svc[constants.ports_key]
                        for i, port in enumerate(ports_section):
                            port = str(port).split(":")[-1]
                            if len(ports_section.ca.items) > 0:
                                if i in ports_section.ca.items:
                                    comment = ports_section.ca.items[i][0].value.strip()
                                    if constants.stack_annotation_marker in comment and constants.http_proxy_key in comment:
                                        parts = comment.split()
                                        parts = parts[parts.index(constants.http_proxy_key) + 1 :]
                                        path = ""
                                        if len(parts) >= 1:
                                            path = parts[0]
                                        if prefix:
                                            path = f"{prefix}/{path.strip('/')}"
                                        path = "/" + path.strip("/")
                                        http_proxy_targets.append({"service": svc_name, "port": port, "path": path})
        return http_proxy_targets

    def get_security_settings(self):
        security_settings = {}
        pods = self.get_pod_list()
        for pod in pods:
            parsed_pod_file = self.load_pod_file(pod)
            if constants.services_key in parsed_pod_file:
                for svc_name, svc in parsed_pod_file[constants.services_key].items():
                    # All we understand for now is 'privileged'
                    if constants.privileged_key in svc:
                        security_settings[svc_name] = {constants.privileged_key: svc[constants.privileged_key]}
        return security_settings

    def get_named_volumes(self):
        # Parse the compose files looking for named volumes
        named_volumes = {"rw": [], "ro": []}

        def find_vol_usage(parsed_pod_file, vol):
            ret = {}
            if constants.services_key in parsed_pod_file:
                for svc_name, svc in parsed_pod_file[constants.services_key].items():
                    if constants.volumes_key in svc:
                        for svc_volume in svc[constants.volumes_key]:
                            parts = svc_volume.split(":")
                            if parts[0] == vol:
                                ret[svc_name] = {
                                    "volume": parts[0],
                                    "mount": parts[1],
                                    "options": parts[2] if len(parts) == 3 else None,
                                }
            return ret

        # A volume is read-only only if *every* mount of it is read-only: one writer
        # means it has to be provisioned writable, however many readers there are.
        # Collect the verdict over all pods and services before classifying, so that
        # the answer does not depend on the order they happen to be visited in.
        is_writable = {}
        pods = self.get_pod_list()
        for pod in pods:
            parsed_pod_file = self.load_pod_file(pod)
            if constants.volumes_key in parsed_pod_file:
                volumes = parsed_pod_file[constants.volumes_key]
                for volume in volumes.keys():
                    for vu in find_vol_usage(parsed_pod_file, volume).values():
                        writable = vu["options"] != "ro"
                        is_writable[volume] = is_writable.get(volume, False) or writable

        for volume, writable in is_writable.items():
            named_volumes["rw" if writable else "ro"].append(volume)

        return named_volumes

    def dump(self, output_file_path):
        enhanced = self.obj.copy()
        for pod in enhanced["pods"]:
            # The script files do not need the full path, just the basename.
            for cmd in ["pre_start_command", "post_start_command"]:
                if cmd in pod:
                    pod[cmd] = os.path.basename(pod[cmd])

        get_yaml().dump(enhanced, open(output_file_path, "wt"))

    def get_plugin_code_paths(self) -> List[Path]:
        result: Set[Path] = set()
        for pod in self.get_pods():
            if type(pod) is str:
                # Pass the stack itself, not its name: get_stack_path() resolves an
                # object via its file_path, but a bare name only to Path(name) -- a
                # relative path that exists nowhere, so the hooks were never found.
                result.add(get_stack_path(self))
            else:
                pod_root_dir = os.path.join(
                    get_dev_root_path(),
                    pod.get("repository", self.get_repo_ref()).split("@")[0],
                    pod.get("path", "."),
                )
                result.add(Path(os.path.join(pod_root_dir, "stack")))

        return list(result)

    def http_prefix_for(self, stack_path_or_name):
        if not self.is_super_stack():
            return None

        if not os.path.exists(str(stack_path_or_name)):
            stack_path_or_name = resolve_stack(stack_path_or_name).file_path.parent

        stacks = self.get_required_stacks()
        for s in stacks:
            stack_path = determine_fs_path_for_stack(s[constants.ref_key], s[constants.path_key])
            if stack_path == stack_path_or_name:
                return s.get(constants.http_proxy_prefix_key, None)
        return None

    def __str__(self):
        return str(self.__dict__)


# Caller can pass either the name of a stack, or a path to a stack file
def get_parsed_stack_config(stack):
    if isinstance(stack, Stack):
        return stack

    stack_file_path = get_stack_path(stack).joinpath(constants.stack_file_name)
    if stack_file_path.exists():
        return Stack(stack).init_from_file(stack_file_path)

    # We try here to generate a useful diagnostic error
    # First check if the stack directory is present
    if stack_file_path.parent.exists():
        error_exit(f"{constants.stack_file_name} file is missing from: {stack}")

    raise Exception(f"stack {stack_file_path} does not exist")


def get_plugin_code_paths(stack) -> List[Path]:
    parsed_stack = get_parsed_stack_config(stack)
    return parsed_stack.get_plugin_code_paths()


def get_pod_file_path(stack, pod_name: str):
    result = None
    pods = stack.get_pods()
    if type(pods[0]) is str:
        result = resolve_compose_file(str(stack.file_path.parent), pod_name)
    else:
        for pod in pods:
            if pod["name"] == pod_name:
                # First check relative to this stack repo
                if stack.repo_path and stack.repo_path.exists():
                    pod_root_dir = str(stack.repo_path.joinpath(pod.get("path", ".")))
                else:
                    pod_root_dir = os.path.join(
                        get_dev_root_path(),
                        pod.get("repository", stack.get_repo_ref()).split("@")[0],
                        pod.get("path", "."),
                    )
                result = os.path.join(pod_root_dir, f"{constants.compose_file_prefix}.yml")
    return result


def determine_fs_path_for_stack(stack_ref, stack_path):
    repo_host, repo_path, repo_branch = repo_util.host_and_path_for_repo(stack_ref)
    return Path(os.path.sep.join([str(get_dev_root_path()), str(repo_host), str(repo_path), str(stack_path)]))


def get_pod_script_paths(parsed_stack, pod_name: str):
    pods = parsed_stack["pods"]
    result = []
    if not type(pods[0]) is str:
        for pod in pods:
            if pod["name"] == pod_name:
                pod_root_dir = os.path.join(
                    get_dev_root_path(),
                    pod.get("repository", parsed_stack.get_repo_ref()).split("@")[0],
                    pod.get("path", "."),
                )
                if "pre_start_command" in pod:
                    result.append(os.path.join(pod_root_dir, pod["pre_start_command"]))
                if "post_start_command" in pod:
                    result.append(os.path.join(pod_root_dir, pod["post_start_command"]))
    return result


def pod_has_scripts(parsed_stack, pod_name: str):
    pods = parsed_stack["pods"]
    if type(pods[0]) is str:
        result = False
    else:
        for pod in pods:
            if pod["name"] == pod_name:
                result = "pre_start_command" in pod or "post_start_command" in pod
    return result


def _is_deployment_stack_copy(stack_file_path: Path, search_path: Path):
    # A deployment directory contains a copy of the stack's files beside its
    # deployment.yml; that copy belongs to the deployment, not to the set of
    # stacks available to build or deploy from.
    for ancestor in Path(stack_file_path).parents:
        if ancestor.joinpath(constants.deployment_file_name).exists():
            return True
        if ancestor == search_path:
            break
    return False


def locate_stacks_beneath(search_path=get_dev_root_path()):
    stacks = []
    if search_path.exists():
        for path in search_path.rglob("stack.yml"):
            if _is_deployment_stack_copy(path, search_path):
                continue
            stacks.append(Stack().init_from_file(path))

    return stacks


def locate_single_stack(stack_name, search_path=get_dev_root_path(), fail_on_multiple=True, fail_on_none=True):
    stacks = locate_stacks_beneath(search_path)
    candidates = [s for s in stacks if s.name == stack_name]
    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        candidate_paths = ", ".join(str(s.file_path.parent) for s in candidates)
        if fail_on_multiple:
            error_exit(f"multiple stacks named {stack_name} found: {candidate_paths}")
        else:
            # The caller treats this the same as finding no stack at all, so make the
            # ambiguity visible rather than letting it surface as "stack not found".
            log_warn(f"WARN: multiple stacks named {stack_name} found: {candidate_paths}")
            return None

    if fail_on_none:
        error_exit(f"stack {stack_name} not found")

    return None


def resolve_stack(stack_name):
    if not stack_name:
        error_exit("stack name cannot be empty")

    if isinstance(stack_name, Stack):
        return stack_name

    if isinstance(stack_name, Path):
        stack_name = str(stack_name)

    stack = None
    if stack_name.startswith("/") or (os.path.exists(stack_name) and os.path.isdir(stack_name)):
        stack = get_parsed_stack_config(stack_name)
        log_debug(f"Resolved {stack_name} to {stack.file_path.parent}")
    else:
        stack = locate_single_stack(stack_name, fail_on_none=False, fail_on_multiple=False)
        if not stack and STACK_USE_BUILTIN_STACK:
            # Last ditch...
            stack_path = get_stack_path(stack_name)
            if stack_path:
                stack = get_parsed_stack_config(stack_path)

    if stack:
        log_debug(f"Resolved {stack_name} to {stack.file_path.parent}")

    if not stack:
        error_exit(f"stack {stack_name} not found in resolve_stack")

    return stack
