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

from stack import constants
from stack.util import (
    get_yaml,
    get_stack_path,
    is_git_repo,
    error_exit,
    get_dev_root_path,
    resolve_compose_file,
)


class Stack:
    name: str
    file_path: Path
    obj: typing.Any
    repo_path: Path

    def __init__(self, name: str) -> None:
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
        self.file_path = file_path.absolute()
        self._determine_repo_path()
        return self

    def _determine_repo_path(self):
        if self.repo_path:
            return self.repo_path

        if self.file_path:
            check_path = self.file_path
        else:
            check_path = Path(self.name)

        while not self.repo_path and check_path and check_path.absolute().as_posix() != "/":
            if is_git_repo(check_path):
                self.repo_path = check_path
            else:
                check_path = check_path.parent

        return self.repo_path

    def get_repo_name(self):
        repo = self.get_repo_url()
        if repo:
            if repo.startswith("https://") or repo.startswith("http://"):
                repo = repo.split("://", 2)[1]
            repo = repo.split(":", 2)[-1]
            if repo.endswith(".git"):
                repo = repo[:-4]
            return repo
        return None

    def get_repo_url(self):
        if self._determine_repo_path():
            repo = git.Repo(self.repo_path)
            return repo.remotes[0].url
        return None

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
        pod_file_path = get_pod_file_path(self, pod_name)
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

    def get_http_proxy_targets(self, prefix=None):
        http_proxy_targets = []
        pods = self.get_pod_list()
        for pod in pods:
            parsed_pod_file = self.load_pod_file(pod)
            if constants.services_key in parsed_pod_file:
                for svc_name, svc in parsed_pod_file[constants.services_key].items():
                    if constants.ports_key in svc:
                        ports_section = svc[constants.ports_key]
                        for i, port in enumerate(ports_section):
                            port = str(port)
                            if len(ports_section.ca.items) > 0:
                                if i in ports_section.ca.items:
                                    comment = ports_section.ca.items[i][0].value.strip()
                                    if constants.stack_annotation_marker in comment and constants.http_proxy_key in comment:
                                        parts = comment.split()
                                        parts = parts[parts.index(constants.http_proxy_key) + 1 :]
                                        path = "/"
                                        if len(parts) >= 1:
                                            path = parts[0]
                                        if prefix:
                                            path = f"{prefix}(/)({path.lstrip("/")}.*)"
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

        pods = self.get_pod_list()
        for pod in pods:
            parsed_pod_file = self.load_pod_file(pod)
            if constants.volumes_key in parsed_pod_file:
                volumes = parsed_pod_file[constants.volumes_key]
                for volume in volumes.keys():
                    for vu in find_vol_usage(parsed_pod_file, volume).values():
                        read_only = vu["options"] == "ro"
                        if read_only:
                            if vu["volume"] not in named_volumes["rw"] and vu["volume"] not in named_volumes["ro"]:
                                named_volumes["ro"].append(vu["volume"])
                        else:
                            if vu["volume"] not in named_volumes["rw"]:
                                named_volumes["rw"].append(vu["volume"])

        return named_volumes

    def dump(self, output_file_path):
        enhanced = self.obj.copy()
        if self.get_repo_name():
            for pod in enhanced["pods"]:
                if type(pod) is not str:
                    if "repository" not in pod:
                        pod["repository"] = self.get_repo_name()
                    # The script files do not need the full path, just the basename.
                    for cmd in ["pre_start_command", "post_start_command"]:
                        if cmd in pod:
                            pod[cmd] = os.path.basename(pod[cmd])
        get_yaml().dump(enhanced, open(output_file_path, "wt"))

    def get_plugin_code_paths(self) -> List[Path]:
        result: Set[Path] = set()
        for pod in self.get_pods():
            if type(pod) is str:
                result.add(get_stack_path(self.name))
            else:
                pod_root_dir = os.path.join(
                    get_dev_root_path(None),
                    pod.get("repository", self.get_repo_name()).split("@")[0].split("/")[-1],
                    pod.get("path", "."),
                )
                result.add(Path(os.path.join(pod_root_dir, "stack")))

        return list(result)

    def __str__(self):
        return str(self.__dict__)


# Caller can pass either the name of a stack, or a path to a stack file
def get_parsed_stack_config(stack):
    stack_file_path = get_stack_path(stack).joinpath(constants.stack_file_name)
    if stack_file_path.exists():
        return Stack(stack).init_from_file(stack_file_path)
    # We try here to generate a useful diagnostic error
    # First check if the stack directory is present
    if stack_file_path.parent.exists():
        error_exit(f"{constants.stack_file_name} file is missing from: {stack}")
    error_exit(f"stack {stack} does not exist")


def get_plugin_code_paths(stack) -> List[Path]:
    parsed_stack = get_parsed_stack_config(stack)
    return parsed_stack.get_plugin_code_paths()


def get_pod_file_path(stack, pod_name: str):
    result = None
    pods = stack.get_pods()
    if type(pods[0]) is str:
        result = resolve_compose_file(stack.name, pod_name)
    else:
        for pod in pods:
            if pod["name"] == pod_name:
                pod_root_dir = os.path.join(
                    get_dev_root_path(None),
                    pod.get("repository", stack.get_repo_name()).split("@")[0].split("/")[-1],
                    pod.get("path", "."),
                )
                result = os.path.join(pod_root_dir, f"{constants.compose_file_prefix}.yml")
    return result


def determine_fs_path_for_stack(stack_ref, stack_path):
    return Path(os.path.sep.join([get_dev_root_path(None), os.path.basename(stack_ref), stack_path]))
