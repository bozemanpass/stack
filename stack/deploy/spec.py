# Copyright © 2022, 2023 Vulcanize
# Copyright © 2025 Bozeman Pass, Inc.
import json

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
import os

from pathlib import Path
from mergedeep import merge, Strategy

from stack import constants
from stack.util import get_yaml

from stack.deploy.stack import Stack


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
    type: str

    def __init__(self, file_path: Path | str = None, obj=None) -> None:
        if obj is None:
            obj = {}
        self.file_path = file_path
        self.obj = obj
        self.type = "single"

    def __getitem__(self, item):
        return self.obj[item]

    def __contains__(self, item):
        return item in self.obj

    def get(self, item, default=None):
        return self.obj.get(item, default)

    def init_from_file(self, file_path: Path):
        self.obj = get_yaml().load(open(file_path, "r"))
        self.file_path = os.path.abspath(file_path)
        return self

    def get_image_registry(self):
        return self.obj.get(constants.image_registry_key)

    def get_config(self):
        return self.obj.get(constants.config_key, {})

    def get_kube_config(self):
        return self.obj.get(constants.kube_config_key, None)

    def get_volumes(self):
        return self.obj.get(constants.volumes_key, {})

    def get_configmaps(self):
        return self.obj.get(constants.configmaps_key, {})

    def fully_qualified_path(self, cfg_map_or_vol_name):
        vol_path = self.get_configmaps().get(cfg_map_or_vol_name)
        if not vol_path:
            vol_path = self.get_volumes().get(cfg_map_or_vol_name)
        if vol_path and not vol_path.startswith("/"):
            vol_path = os.path.join(os.path.dirname(self.file_path), vol_path)

        return vol_path

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

    def load_stack(self):
        return Stack(self.obj["stack"]).init_from_file(os.path.join(self.obj["stack"], constants.stack_file_name))

    def get_pod_list(self):
        return self.load_stack().get_pod_list()

    def load_pod_file(self, pod_name):
        return self.load_stack().load_pod_file(pod_name)

    def copy(self):
        ret = Spec()
        ret.obj = self.obj.copy()
        ret.file_path = self.file_path

        return ret

    def dump(self, output_file_path):
        get_yaml().dump(self.obj, open(output_file_path, "w"))

    def __str__(self):
        return json.dumps(self, default=vars, indent=2)


class MergedSpec(Spec):
    def __init__(self):
        super().__init__()
        self.type = "merged"
        self._specs = []

    def load_stack(self):
        raise Exception("Not supported")

    def stack_for_pod(self, pod_name):
        for spec in self._specs:
            if pod_name in spec.get_pod_list():
                return spec.load_stack()
        return None

    def get_pod_list(self):
        ret = []
        for spec in self._specs:
            ret.extend(spec.get_pod_list())
        return ret

    def load_pod_file(self, pod_name):
        for spec in self._specs:
            pod_file = spec.load_pod_file(pod_name)
            if pod_file:
                return pod_file
        return None

    def fully_qualified_path(self, cfg_map_or_vol_name):
        for spec in self._specs:
            vol_path = spec.fully_qualified_path(cfg_map_or_vol_name)
            if vol_path:
                return vol_path
        return None

    def merge(self, other):
        if self.get_deployment_type() and self.get_deployment_type() != other.get_deployment_type():
            raise TypeError(f"{self.get_deployment_type()} != {other.get_deployment_type()}")

        if self.get_image_registry() and self.get_image_registry() != other.get_image_registry():
            raise TypeError(f"{self.get_image_registry()} != {other.get_image_registry()}")

        merge(self.obj, other.obj, strategy=Strategy.ADDITIVE)
        self._specs.append(other)

        self.obj["stack"] = [x["stack"] for x in self._specs]

        return self

    def copy(self):
        ret = MergedSpec()
        self.file_path = None
        ret.obj = self.obj.copy()
        ret._specs = self._specs.copy()

        return ret
