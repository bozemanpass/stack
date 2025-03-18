# Copyright © 2023 Vulcanize

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
from stack.util import get_yaml, get_pod_file_path


class Stack:
    name: str
    file_path: str | Path
    obj: typing.Any

    def __init__(self, name: str) -> None:
        self.name = name

    def __getitem__(self, item):
        return self.obj[item]

    def __contains__(self, item):
        return item in self.obj

    def get(self, item, default=None):
        return self.obj.get(item, default)

    def init_from_file(self, file_path: Path):
        self.obj = get_yaml().load(open(file_path, "r"))
        self.file_path = file_path

        return self

    def get_pods(self):
        return self.obj.get("pods", [])

    def get_pod_list(self):
        # Handle both old and new format
        pods = self.get_pods()
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

    def dump(self, output_file_path):
        get_yaml().dump(self.obj, open(output_file_path, "wt"))

    def __str__(self):
        return json.dumps(self, default=vars, indent=2)
