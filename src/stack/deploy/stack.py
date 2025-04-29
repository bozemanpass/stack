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

import json
import typing

from pathlib import Path

import git
from stack.repos.setup_repositories import is_git_repo
from stack.util import get_yaml, get_pod_file_path
from stack import constants


class Stack:
    name: str
    file_path: Path
    obj: typing.Any
    repo_path: Path

    def __init__(self, name: str) -> None:
        self.name = name
        self.obj = {}
        self.file_path = None
        self.repo_path = None

    def __getitem__(self, item):
        return self.obj[item]

    def __contains__(self, item):
        return item in self.obj

    def get(self, item, default=None):
        return self.obj.get(item, default)

    def init_from_file(self, file_path: Path):
        if isinstance(file_path, str):
            file_path = Path(file_path)
        self.obj = get_yaml().load(open(file_path, "rt"))
        self.file_path = file_path.absolute()

        parent = self.file_path.parent
        while not self.repo_path and parent and parent.absolute().as_posix() != "/":
            if is_git_repo(parent):
                self.repo_path = parent
            else:
                parent = parent.parent

        return self

    def get_repo_name(self):
        repo = self.get_repo_url()
        if repo:
            if repo.startswith("https://") or repo.startswith("http://"):
                repo = repo.split("://", 2)[1]
            repo = repo.split(":", 2)[1]
            if repo.endswith(".git"):
                repo = repo[:-4]
            return repo
        return None

    def get_repo_url(self):
        if self.repo_path:
            repo = git.Repo(self.repo_path)
            return repo.remotes[0].url
        return None

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
        pod_file_path = get_pod_file_path(self.name, self, pod_name)
        if pod_file_path:
            return get_yaml().load(open(pod_file_path, "rt"))
        return None

    def get_pod_file_path(self, pod_name):
        return get_pod_file_path(self.name, self, pod_name)

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
        get_yaml().dump(self.obj, open(output_file_path, "wt"))

    def __str__(self):
        return json.dumps(self, default=vars, indent=2)
