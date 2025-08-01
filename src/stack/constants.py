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

import os

annotations_key = "annotations"
cluster_id_key = "cluster-id"
cluster_name_prefix = "stack-"
compose_deploy_type = "compose"
compose_dir_name = "compose"
compose_file_prefix = os.environ.get("STACK_COMPOSE_FILE_PREFIX", "composefile")
config_file_name = "config.env"
config_key = "config"
configmaps_key = "configmaps"
container_lock_file_name = "container.lock"
container_file_name = "container.yml"
cluster_issuer_key = "cluster-issuer"
deploy_to_key = "deploy-to"
deployment_file_name = "deployment.yml"
host_name_key = "host-name"
http_proxy_key = "http-proxy"
http_proxy_prefix_key = "http-proxy-prefix"
image_registry_key = "image-registry"
k8s_deploy_type = "k8s"
k8s_kind_deploy_type = "k8s-kind"
kind_config_filename = "kind-config.yml"
kube_config_filename = "kubeconfig.yml"
kube_config_key = "kube-config"
labels_key = "labels"
network_key = "network"
node_affinities_key = "node-affinities"
node_tolerations_key = "node-tolerations"
path_key = "path"
ports_key = "ports"
privileged_key = "privileged"
proxy_to_key = "proxy-to"
ref_key = "ref"
replicas_key = "replicas"
requires_key = "requires"
resources_key = "resources"
routes_key = "routes"
security_key = "security"
services_key = "services"
spec_file_name = "spec.yml"
stack_file_name = "stack.yml"
stack_key = "stack"
stacks_key = "stacks"
volumes_key = "volumes"

stack_annotation_marker = "@stack"
