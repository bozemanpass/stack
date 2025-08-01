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
import base64

from kubernetes import client
from pathlib import Path
from typing import Any, List, Set

from stack import constants
from stack.log import log_debug, log_warn
from stack.util import env_var_map_from_file
from stack.deploy.k8s.helpers import (
    named_volumes_from_pod_files,
    volume_mounts_for_service,
    volumes_for_service,
    container_ports_for_service,
)
from stack.deploy.k8s.helpers import get_kind_pv_bind_mount_path
from stack.deploy.k8s.helpers import (
    envs_from_environment_variables_map,
    envs_from_compose_file,
    merge_envs,
)
from stack.deploy.deploy_util import (
    parsed_pod_files_map_from_file_names,
    images_for_deployment,
)
from stack.deploy.deploy_types import DeployEnvVars
from stack.deploy.deploy_util import convert_to_seconds
from stack.deploy.k8s.helpers import env_var_name_for_service, DEFAULT_K8S_NAMESPACE
from stack.deploy.spec import Spec, Resources, ResourceLimits
from stack.deploy.images import remote_tag_for_image_unique


DEFAULT_VOLUME_RESOURCES = Resources({"reservations": {"storage": "2Gi"}})

DEFAULT_CONTAINER_RESOURCES = Resources(
    {
        "reservations": {"cpus": "0.1", "memory": "200M"},
        "limits": {"cpus": "1.0", "memory": "2000M"},
    }
)


def to_k8s_resource_requirements(resources: Resources) -> client.V1ResourceRequirements:
    def to_dict(limits: ResourceLimits):
        if not limits:
            return None

        ret = {}
        if limits.cpus:
            ret["cpu"] = str(limits.cpus)
        if limits.memory:
            ret["memory"] = f"{int(limits.memory / (1000 * 1000))}M"
        if limits.storage:
            ret["storage"] = f"{int(limits.storage / (1000 * 1000))}M"
        return ret

    return client.V1ResourceRequirements(requests=to_dict(resources.reservations), limits=to_dict(resources.limits))


class ClusterInfo:
    k8s_namespace: str = DEFAULT_K8S_NAMESPACE
    parsed_pod_yaml_map: Any
    image_set: Set[str] = set()
    app_name: str
    namespace: str
    environment_variables: DeployEnvVars
    spec: Spec

    def __init__(self) -> None:
        pass

    def int(self, pod_files: List[str], compose_env_file, deployment_name, spec: Spec):
        self.parsed_pod_yaml_map = parsed_pod_files_map_from_file_names(pod_files)
        # Find the set of images in the pods
        self.image_set = images_for_deployment(pod_files)
        self.environment_variables = DeployEnvVars({})
        self.app_name = deployment_name
        self.spec = spec

        # Set the dynamic service ENV
        service_env = {}
        for svc in self.get_services():
            if "ClusterIP" == svc.spec.type:
                service_env[env_var_name_for_service(svc)] = f"{svc.metadata.name}.{self.k8s_namespace}.svc.cluster.local"

        # Load the shared static ENV (raw)
        env_vars_from_file = env_var_map_from_file(compose_env_file, expand=False)

        self.environment_variables = DeployEnvVars(
            # Now expand the static ENV using the dynamic ENV
            merge_envs(envs_from_compose_file(env_vars_from_file, service_env), service_env)
        )

        log_debug(f"Env vars: {self.environment_variables.map}")

    def get_ingress(self, use_tls=False, certificate=None, def_cluster_issuer="letsencrypt-prod"):
        # No ingress for a deployment that has no http-proxy defined, for now
        http_proxy_info_list = self.spec.get_http_proxy()
        ingress = None
        if http_proxy_info_list:
            # TODO: handle multiple definitions
            http_proxy_info = http_proxy_info_list[0]
            log_debug(f"http-proxy: {http_proxy_info}")
            # TODO: good enough parsing for webapp setupment for now
            host_name = http_proxy_info[constants.host_name_key]
            rules = []
            tls = (
                [
                    client.V1IngressTLS(
                        hosts=certificate["spec"]["dnsNames"] if certificate else [host_name],
                        secret_name=certificate["spec"]["secretName"] if certificate else f"{self.app_name}-tls",
                    )
                ]
                if use_tls
                else None
            )
            paths = []
            for route in http_proxy_info[constants.routes_key]:
                path = route.get(constants.path_key, "/")
                if path == "/" or path == "":
                    path = "/()(.*)"
                elif "(.*)" not in path:
                    path = f"/{path.strip('/')}(/?)(.*)"
                proxy_to = route[constants.proxy_to_key]
                log_debug(f"proxy config: {path} -> {proxy_to}")
                # proxy_to has the form <container>:<port>
                proxy_to_svc, proxy_to_port = proxy_to.split(":")
                paths.append(
                    client.V1HTTPIngressPath(
                        path_type="ImplementationSpecific",
                        path=path,
                        backend=client.V1IngressBackend(
                            service=client.V1IngressServiceBackend(
                                name=f"{self.app_name}-svc-{proxy_to_svc}",
                                port=client.V1ServiceBackendPort(number=int(proxy_to_port)),
                            )
                        ),
                    )
                )

            rules.append(client.V1IngressRule(host=host_name, http=client.V1HTTPIngressRuleValue(paths=paths)))
            spec = client.V1IngressSpec(tls=tls, rules=rules, ingress_class_name="nginx")

            ingress_annotations = {
                "kubernetes.io/ingress.class": "nginx",
                "nginx.ingress.kubernetes.io/rewrite-target": "/$2",
                "nginx.ingress.kubernetes.io/use-regex": "true",
            }

            if not certificate:
                ingress_annotations["cert-manager.io/cluster-issuer"] = http_proxy_info.get(
                    constants.cluster_issuer_key, def_cluster_issuer
                )

            ingress = client.V1Ingress(
                metadata=client.V1ObjectMeta(name=f"{self.app_name}-ingress", annotations=ingress_annotations),
                spec=spec,
            )
        return ingress

    def get_services(self):
        ret = []
        for pod_name in self.parsed_pod_yaml_map:
            pod = self.parsed_pod_yaml_map[pod_name]
            services = pod["services"]
            for service_name in services:
                service_info = services[service_name]
                if "ports" in service_info:
                    int_ports = [int(p.split(":")[-1].replace("/udp", "")) for p in service_info["ports"]]
                    svc_ports = [client.V1ServicePort(port=p, target_port=p, name=f"{service_name}-{p}") for p in int_ports]
                    service = client.V1Service(
                        metadata=client.V1ObjectMeta(
                            name=f"{self.app_name}-svc-{service_name}",
                            labels={"app": self.app_name, "service": service_name},
                        ),
                        spec=client.V1ServiceSpec(
                            type="ClusterIP",
                            ports=svc_ports,
                            # TODO: For balancing, we should use some sort of shared tag among pods of the same type
                            selector={"app": self.app_name, "service": service_name},
                        ),
                    )
                    ret.append(service)
        return ret

    def get_pvcs(self):
        result = []
        spec_volumes = self.spec.get_volumes()
        named_volumes = named_volumes_from_pod_files(self.parsed_pod_yaml_map)
        log_debug(f"Spec Volumes: {spec_volumes}")
        log_debug(f"Named Volumes: {named_volumes}")
        for volume_name, volume_path in spec_volumes.items():
            if volume_name not in named_volumes:
                log_debug(f"{volume_name} not in pod files")
                continue
            resources = self.spec.get_volume_resources(volume_name)
            if not resources:
                resources = DEFAULT_VOLUME_RESOURCES

            log_debug(f"{volume_name} Resources: {resources}")

            labels = {
                "app": self.app_name,
                "volume-label": f"{self.app_name}-{volume_name}",
            }
            if volume_path:
                storage_class_name = "manual"
                k8s_volume_name = f"{self.app_name}-{volume_name}"
            else:
                # These will be auto-assigned.
                storage_class_name = None
                k8s_volume_name = None

            spec = client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteOnce"],
                storage_class_name=storage_class_name,
                resources=to_k8s_resource_requirements(resources),
                volume_name=k8s_volume_name,
            )
            pvc = client.V1PersistentVolumeClaim(
                metadata=client.V1ObjectMeta(name=f"{self.app_name}-{volume_name}", labels=labels),
                spec=spec,
            )
            result.append(pvc)
        return result

    def get_configmaps(self):
        result = []
        spec_configmaps = self.spec.get_configmaps()
        named_volumes = named_volumes_from_pod_files(self.parsed_pod_yaml_map)
        for cfg_map_name in spec_configmaps.keys():
            if cfg_map_name not in named_volumes:
                log_debug(f"{cfg_map_name} not in pod files")
                continue

            cfg_map_path = self.spec.fully_qualified_path(cfg_map_name)

            # Read in all the files at a single-level of the directory.  This mimics the behavior
            # of `kubectl create configmap foo --from-file=/path/to/dir`
            data = {}
            for f in os.listdir(cfg_map_path):
                full_path = os.path.join(cfg_map_path, f)
                if os.path.isfile(full_path):
                    data[f] = base64.b64encode(open(full_path, "rb").read()).decode("ASCII")

            spec = client.V1ConfigMap(
                metadata=client.V1ObjectMeta(
                    name=f"{self.app_name}-{cfg_map_name}",
                    labels={"configmap-label": cfg_map_name},
                ),
                binary_data=data,
            )
            result.append(spec)
        return result

    def get_pvs(self):
        result = []
        spec_volumes = self.spec.get_volumes()
        named_volumes = named_volumes_from_pod_files(self.parsed_pod_yaml_map)
        for volume_name, volume_path in spec_volumes.items():
            # We only need to create a volume if it is fully qualified HostPath.
            # Otherwise, we create the PVC and expect the node to allocate the volume for us.
            if not volume_path:
                log_debug(f"{volume_name} does not require an explicit PersistentVolume, since it is not a bind-mount.")
                continue

            if volume_name not in named_volumes:
                log_debug(f"{volume_name} not in pod files")
                continue

            if not os.path.isabs(volume_path):
                log_warn(f"WARN: {volume_name}:{volume_path} is not absolute, cannot bind volume.")
                continue

            resources = self.spec.get_volume_resources(volume_name)
            if not resources:
                resources = DEFAULT_VOLUME_RESOURCES

            if self.spec.is_kind_deployment():
                host_path = client.V1HostPathVolumeSource(path=get_kind_pv_bind_mount_path(volume_name))
            else:
                host_path = client.V1HostPathVolumeSource(path=volume_path)
            spec = client.V1PersistentVolumeSpec(
                storage_class_name="manual",
                access_modes=["ReadWriteOnce"],
                capacity=to_k8s_resource_requirements(resources).requests,
                host_path=host_path,
            )
            pv = client.V1PersistentVolume(
                metadata=client.V1ObjectMeta(
                    name=f"{self.app_name}-{volume_name}",
                    labels={"volume-label": f"{self.app_name}-{volume_name}"},
                ),
                spec=spec,
            )
            result.append(pv)
        return result

    # TODO: put things like image pull policy into an object-scope struct
    def get_deployments(self, image_pull_policy: str = None):
        deployments = []

        for pod_name in self.parsed_pod_yaml_map:
            pod_dir = Path(pod_name).parent
            pod = self.parsed_pod_yaml_map[pod_name]
            services = pod["services"]
            for service_name in services:
                container_name = service_name
                service_info = services[service_name]
                image = service_info["image"]
                container_ports = container_ports_for_service(service_info)

                merged_envs = self.environment_variables.map.copy()
                if "env_file" in service_info:
                    for env_file in service_info["env_file"]:
                        env_file = f"{pod_dir}/{env_file}"
                        env_vars_from_file = env_var_map_from_file(env_file, expand=False)
                        merged_envs = merge_envs(envs_from_compose_file(env_vars_from_file, merged_envs), merged_envs)

                if "environment" in service_info:
                    merged_envs = merge_envs(envs_from_compose_file(service_info["environment"], merged_envs), merged_envs)

                envs = envs_from_environment_variables_map(merged_envs)
                log_debug(f"Merged envs: {envs}")

                liveness_probe = None
                if "healthcheck" in service_info:
                    healthcheck = service_info["healthcheck"]
                    # TODO: Support other probe types
                    test = healthcheck.get("test")
                    if test:
                        # In a compose file, this will be something like:
                        #   test: ["CMD", "wget", "--tries=1", "--connect-timeout=1", "-q", "-O", "-", "http://localhost"]
                        # We want to strip off the type, but keep the command and arguments.
                        if test[0] == "CMD-SHELL":
                            command = ["/bin/sh", "-c"] + test[1:]
                        else:
                            command = test[1:]

                        liveness_probe = client.V1Probe(
                            _exec=client.V1ExecAction(command=command),
                            initial_delay_seconds=convert_to_seconds(healthcheck.get("start_period", "0s")),
                            period_seconds=convert_to_seconds(healthcheck.get("interval", "30s")),
                            timeout_seconds=convert_to_seconds(healthcheck.get("timeout", "30s")),
                            failure_threshold=int(healthcheck.get("retries", "3")),
                        )

                # Re-write the image tag for remote deployment
                # Note self.app_name has the same value as deployment_id
                image_to_use = (
                    remote_tag_for_image_unique(image, self.spec.get_image_registry(), self.app_name)
                    if self.spec.get_image_registry() is not None
                    else image
                )
                volume_mounts = volume_mounts_for_service(self.parsed_pod_yaml_map, service_name)
                resources = self.spec.get_container_resources(service_name)
                if not resources:
                    resources = DEFAULT_CONTAINER_RESOURCES
                container = client.V1Container(
                    name=container_name,
                    image=image_to_use,
                    image_pull_policy=image_pull_policy,
                    env=envs,
                    ports=container_ports,
                    volume_mounts=volume_mounts,
                    security_context=client.V1SecurityContext(
                        privileged=self.spec.get_privileged(container_name),
                        capabilities=(
                            client.V1Capabilities(add=self.spec.get_capabilities(container_name))
                            if self.spec.get_capabilities(container_name)
                            else None
                        ),
                    ),
                    resources=to_k8s_resource_requirements(resources),
                    liveness_probe=liveness_probe,
                )
                volumes = volumes_for_service(self.parsed_pod_yaml_map, service_name, self.spec, self.app_name)
                image_pull_secrets = [client.V1LocalObjectReference(name="stack-image-registry")]

                annotations = None
                # TODO: For balancing, we should use some sort of shared tag among pods of the same type
                labels = {"app": self.app_name, "service": service_name}
                affinity = None
                tolerations = None

                # TODO: Make these container-specific in the spec
                if self.spec.get_annotations():
                    annotations = {}
                    for key, value in self.spec.get_annotations().items():
                        annotations[key.replace("{name}", container.name)] = value

                # TODO: Make these container-specific in the spec
                if self.spec.get_labels():
                    for key, value in self.spec.get_labels().items():
                        labels[key.replace("{name}", container.name)] = value

                # TODO: Make these container-specific in the spec
                if self.spec.get_node_affinities():
                    affinities = []
                    for rule in self.spec.get_node_affinities():
                        # TODO add some input validation here
                        label_name = rule["label"]
                        label_value = rule["value"]
                        affinities.append(
                            client.V1NodeSelectorTerm(
                                match_expressions=[
                                    client.V1NodeSelectorRequirement(key=label_name, operator="In", values=[label_value])
                                ]
                            )
                        )
                    affinity = client.V1Affinity(
                        node_affinity=client.V1NodeAffinity(
                            required_during_scheduling_ignored_during_execution=client.V1NodeSelector(
                                node_selector_terms=affinities
                            )
                        )
                    )

                # TODO: Make these container-specific in the spec
                if self.spec.get_node_tolerations():
                    tolerations = []
                    for toleration in self.spec.get_node_tolerations():
                        # TODO add some input validation here
                        toleration_key = toleration["key"]
                        toleration_value = toleration["value"]
                        tolerations.append(
                            client.V1Toleration(
                                effect="NoSchedule",
                                key=toleration_key,
                                operator="Equal",
                                value=toleration_value,
                            )
                        )

                # every service gets aliases of $name and $name.local to localhost
                localhost_aliases = client.V1HostAlias(hostnames=[container.name, f"{container.name}.local"], ip="127.0.0.1")

                template = client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(annotations=annotations, labels=labels),
                    spec=client.V1PodSpec(
                        containers=[container],
                        image_pull_secrets=image_pull_secrets,
                        volumes=volumes,
                        affinity=affinity,
                        tolerations=tolerations,
                        host_aliases=[localhost_aliases],
                    ),
                )

                spec = client.V1DeploymentSpec(
                    replicas=self.spec.get_replicas(),
                    template=template,
                    selector={"matchLabels": {"app": self.app_name}},
                )

                deployment = client.V1Deployment(
                    api_version="apps/v1",
                    kind="Deployment",
                    metadata=client.V1ObjectMeta(name=f"{self.app_name}-deploy-{service_name}"),
                    spec=spec,
                )

                deployments.append(deployment)

        return deployments
