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

import base64
import importlib.resources
import json
import os
import platform
import subprocess

from pathlib import Path
from python_on_whales import DockerClient

from stack.opts import opts
from stack.util import get_parsed_stack_config, warn_exit, get_yaml, error_exit


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


def container_exists_locally(tag):
    docker = DockerClient()
    return docker.image.exists(tag)


def container_exists_remotely(tag, registry=None, arch=None):
    if not arch:
        arch = local_container_arch()

    manifests = _docker_manifest_inspect(tag, registry)
    for manifest in manifests:
        platform = manifest.get("Descriptor", {}).get("platform", {})
        if arch == platform.get("architecture") and "linux" == platform.get("os"):
            return True

    return False


def _docker_manifest_inspect(tag, registry=None):
    manifest = None
    full_tag = tag
    if registry:
        full_tag = f"{registry}/{tag}"

    # Basic docker command
    manifest_cmd = ["docker", "manifest", "inspect", "--verbose", full_tag]

    # podman does not properly support the manifest command, so we cheat by having podman run the docker-cli
    docker_version = subprocess.run(["docker", "--version"], capture_output=True, text=True)
    if "podman" in docker_version.stdout or True:
        inspect_str = f"docker manifest inspect --verbose {full_tag}"
        if registry:
            username = None
            password = None
            registry_root = registry
            if "/" in registry:
                registry_root = registry.split("/")[0]
            if os.path.exists(f"{os.environ['XDG_RUNTIME_DIR']}/containers/auth.json"):
                auths = json.load(open(f"{os.environ['XDG_RUNTIME_DIR']}/containers/auth.json", "rt")).get("auths", {})
                login_info = None
                if registry in auths and "auth" in auths[registry]:
                    login_info = auths[registry]["auth"]
                elif registry_root in auths and "auth" in auths[registry_root]:
                    login_info = auths[registry_root]["auth"]
                if login_info:
                    username, password = base64.standard_b64decode(login_info).decode().split(":", 2)

            if username and password:
                inspect_str = f"""docker login --username "{username}" --password "{password}" {registry} >/dev/null && {inspect_str}"""

        manifest_cmd = ["podman", "run", "-q", "alpinelinux/docker-cli", "sh", "-c", inspect_str]

    result = subprocess.run(manifest_cmd, capture_output=True, text=True)
    if 0 == result.returncode:
        manifest = json.loads(result.stdout)
        if not isinstance(manifest, list):
            manifest = [manifest]

    return manifest if manifest else []


def local_container_arch():
    this_machine = platform.machine()
    # Translate between Python and docker platform names
    if this_machine == "x86_64":
        this_machine = "amd64"
    if this_machine == "aarch64":
        this_machine = "arm64"
    return this_machine
