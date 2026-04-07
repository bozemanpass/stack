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

import yaml

from kubernetes import client

from stack.deploy.k8s.deploy_k8s import K8sDeployer
from stack.log import output_main
from stack.util import error_exit


def _k8s_object_to_yaml(obj):
    api_client = client.ApiClient()
    sanitized = api_client.sanitize_for_serialization(obj)
    return yaml.dump(sanitized, default_flow_style=False, sort_keys=False)


def _print_section(title, objects):
    if not objects:
        return
    output_main(f"--- {title} ---")
    for obj in objects:
        output_main(_k8s_object_to_yaml(obj))


def explain_op(ctx):
    deployer = ctx.obj.deployer

    if not isinstance(deployer, K8sDeployer):
        error_exit("The explain command is currently only supported for k8s deployments")

    cluster_info = deployer.cluster_info
    is_kind = deployer.is_kind()

    pvs = cluster_info.get_pvs()
    _print_section("PersistentVolumes", pvs)

    pvcs = cluster_info.get_pvcs()
    _print_section("PersistentVolumeClaims", pvcs)

    config_maps = cluster_info.get_configmaps()
    _print_section("ConfigMaps", config_maps)

    deployments = cluster_info.get_deployments(image_pull_policy=None if is_kind else "Always")
    _print_section("Deployments", deployments)

    services = cluster_info.get_services()
    _print_section("Services", services)

    http_proxy_info = cluster_info.spec.get_http_proxy()
    use_tls = http_proxy_info and not is_kind
    ingress = cluster_info.get_ingress(use_tls=use_tls)
    if ingress:
        _print_section("Ingress", [ingress])
