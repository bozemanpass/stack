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

import typing
import humanfriendly

from pathlib import Path

from stack.util import get_yaml
from stack import constants


class ResourceLimits:
    cpus: float = None
    memory: int = None
    storage: int = None

    def __init__(self, obj=None):
        if obj is None:
            obj = {}
        if "cpus" in obj:
            self.cpus = float(obj["cpus"])
        if "memory" in obj:
            self.memory = humanfriendly.parse_size(obj["memory"])
        if "storage" in obj:
            self.storage = humanfriendly.parse_size(obj["storage"])

    def __len__(self):
        return len(self.__dict__)

    def __iter__(self):
        for k in self.__dict__:
            yield k, self.__dict__[k]

    def __repr__(self):
        return str(self.__dict__)


class Resources:
    limits: ResourceLimits = None
    reservations: ResourceLimits = None

    def __init__(self, obj=None):
        if obj is None:
            obj = {}
        if "reservations" in obj:
            self.reservations = ResourceLimits(obj["reservations"])
        if "limits" in obj:
            self.limits = ResourceLimits(obj["limits"])

    def __len__(self):
        return len(self.__dict__)

    def __iter__(self):
        for k in self.__dict__:
            yield k, self.__dict__[k]

    def __repr__(self):
        return str(self.__dict__)


class Spec:
    obj: typing.Any
    file_path: Path

    def __init__(self, file_path: Path = None, obj=None) -> None:
        if obj is None:
            obj = {}
        self.file_path = file_path
        self.obj = obj

    def __getitem__(self, item):
        return self.obj[item]

    def __contains__(self, item):
        return item in self.obj

    def get(self, item, default=None):
        return self.obj.get(item, default)

    def init_from_file(self, file_path: Path):
        with file_path:
            self.obj = get_yaml().load(open(file_path, "r"))
            self.file_path = file_path

    def get_image_registry(self):
        return self.obj.get(constants.image_registry_key)

    def get_volumes(self):
        return self.obj.get(constants.volumes_key, {})

    def get_configmaps(self):
        return self.obj.get(constants.configmaps_key, {})

    def get_container_resources(self, service_name):
        return Resources(self.obj.get(constants.resources_key, {}).get("containers", {}).get(service_name, {}))

    def get_volume_resources(self, volume_name):
        return Resources(self.obj.get(constants.resources_key, {}).get(constants.volumes_key, {}).get(volume_name, {}))

    def get_http_proxy(self):
        return self.obj.get(constants.network_key, {}).get(constants.http_proxy_key, [])

    def get_annotations(self):
        return self.obj.get(constants.annotations_key, {})

    def get_replicas(self):
        return self.obj.get(constants.replicas_key, 1)

    def get_node_affinities(self):
        return self.obj.get(constants.node_affinities_key, [])

    def get_node_tolerations(self):
        return self.obj.get(constants.node_tolerations_key, [])

    def get_labels(self):
        return self.obj.get(constants.labels_key, {})

    def get_privileged(self, container_name):
        return "true" == str(self.obj.get(constants.security_key, {}).get(container_name, {}).get("privileged", "false")).lower()

    def get_capabilities(self, container_name):
        return self.obj.get(constants.security_key, {}).get(container_name, {}).get("capabilities", [])

    def get_deployment_type(self):
        return self.obj.get(constants.deploy_to_key)

    def is_kubernetes_deployment(self):
        return self.get_deployment_type() in [
            constants.k8s_kind_deploy_type,
            constants.k8s_deploy_type,
        ]

    def is_kind_deployment(self):
        return self.get_deployment_type() in [constants.k8s_kind_deploy_type]

    def is_docker_deployment(self):
        return self.get_deployment_type() in [constants.compose_deploy_type]
