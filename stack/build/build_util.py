# Copyright © 2024 Vulcanize

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

import importlib.resources
import json

from pathlib import Path

from stack.opts import opts
from stack.util import get_parsed_stack_config, warn_exit, get_yaml


class StackContainer:
    name: str
    ref: str
    path: str

    def __init__(self, name: str=None, ref=None, path=None):
        self.name = name
        self.ref = ref
        self.path = path

    def __repr__(self):
        return str(self)

    def __str__(self):
        ret = { "name": self.name, "ref": self.ref, "path": self.path }
        return json.dumps(ret)


class ContainerSpec:
    name: str
    ref: str
    build: str
    file_path: str

    def __init__(self, name: str=None, ref=None, build=None):
        self.name = name
        self.ref = ref
        self.build = build
        self.file_path = None

    def __repr__(self):
        return str(self)

    def __str__(self):
        ret = { "name": self.name, "ref": self.ref, "build": self.build, "file_path": self.file_path }
        return json.dumps(ret)

    def init_from_file(self, file_path: Path):
        self.file_path = file_path
        y = get_yaml().load(open(file_path, "r"))
        self.name = y["container"]["name"]
        self.ref = y["container"].get("ref")
        self.build = y["container"].get("build")
        return self


def get_containers_in_scope(stack: str):

    containers_in_scope = []
    if stack:
        stack_config = get_parsed_stack_config(stack)
        if "containers" not in stack_config or stack_config["containers"] is None:
            warn_exit(f"stack {stack} does not define any containers")
        raw_containers = stack_config['containers']
    else:
        # See: https://stackoverflow.com/a/20885799/1701505
        from stack import data
        with importlib.resources.open_text(data, "container-image-list.txt") as container_list_file:
            raw_containers = container_list_file.read().splitlines()


    for container in raw_containers:
        if isinstance(container, str):
            containers_in_scope.append(StackContainer(container))
        else:
            containers_in_scope.append(StackContainer(container["name"], ref=container.get("ref"), path=container.get("path")))

    if opts.o.verbose:
        print(f'Containers: {containers_in_scope}')
        if stack:
            print(f"Stack: {stack}")

    return containers_in_scope
