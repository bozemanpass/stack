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
wrapper_lock_file_name = "wrapper.lock"
stack_lock_file_name = "stack.lock"
containers_directory_name = "containers"
container_file_name = "container.yml"
cluster_issuer_key = "cluster-issuer"
deploy_to_key = "deploy-to"
backup_key = "backup"
backup_service_name = "backup"
backup_exclude_annotation = "backup-exclude"
backup_command_annotation = "backup-command"
backup_file_extension_annotation = "backup-file-extension"
# Extension given to a dump whose stack did not name one.  Applied on both targets, so
# that the same stack produces a snapshot of the same name whichever engine took it.
backup_default_file_extension = "dump"
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
# The pod labels stack generates for itself.  Both the Deployment and the Service
# select their pods on these, so a spec's `labels` may not redefine them -- see
# _check_labels in deployment_create.
reserved_label_keys = ("app", "service")
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
runtime_class_key = "runtime-class"
secrets_key = "secrets"
secrets_file_name = "secrets.env"
security_key = "security"
services_key = "services"
spec_file_name = "spec.yml"
stack_file_name = "stack.yml"
stack_files_directory_name = "stack-files"
stack_key = "stack"
stacks_key = "stacks"
volumes_key = "volumes"

stack_annotation_marker = "@stack"
# On an image: line, opts that external image out of digest locking (see docs/stack-integrity.md).
unpinned_annotation = "unpinned"
