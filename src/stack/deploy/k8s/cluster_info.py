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
from stack.deploy.k8s import k8up
from stack.deploy.secrets import K8S_SECRET_NAME
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
from stack.deploy.k8s.helpers import DEFAULT_K8S_NAMESPACE
from stack.deploy.spec import Spec, Resources, ResourceLimits
from stack.deploy.images import resolve_image_for_deployment
from stack.deploy.k8s import gateway


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
        self.k8s_namespace = deployment_name
        self.spec = spec

        # Load the shared static ENV (raw)
        env_vars_from_file = env_var_map_from_file(compose_env_file, expand=False)

        self.environment_variables = DeployEnvVars(envs_from_compose_file(env_vars_from_file, {}))

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
                        secret_name=certificate["spec"]["secretName"] if certificate else "tls",
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
                                name=proxy_to_svc,
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
                metadata=client.V1ObjectMeta(name="ingress", annotations=ingress_annotations),
                spec=spec,
            )
        return ingress

    def get_http_route(self, gateway_name, gateway_namespace):
        """The HTTPRoute for this deployment's http-proxy config, as a dict.

        The Gateway API equivalent of get_ingress().  Routing attaches to the
        shared Gateway named by the arguments; TLS is not represented here at
        all -- in the Gateway API it belongs to the Gateway's listeners, which
        are managed at deploy time (see stack.deploy.k8s.gateway).

        There are no typed classes for Gateway API resources in the kubernetes
        client, so this returns the resource as a plain dict.
        """
        http_proxy_info_list = self.spec.get_http_proxy()
        if not http_proxy_info_list:
            return None
        # TODO: handle multiple definitions
        http_proxy_info = http_proxy_info_list[0]
        log_debug(f"http-proxy: {http_proxy_info}")
        host_name = http_proxy_info[constants.host_name_key]
        rules = []
        for route in http_proxy_info[constants.routes_key]:
            path = route.get(constants.path_key, "/")
            if "(" in path:
                # The Ingress API arrangement accepted nginx regex paths; the
                # Gateway API has no core regex matching, so degrade to the
                # literal prefix in front of the regex.
                prefix = path.split("(")[0]
                log_warn(f"http-proxy path {path} contains a regex; using prefix match on {prefix or '/'}")
                path = prefix
            path = f"/{path.strip('/')}"
            proxy_to = route[constants.proxy_to_key]
            log_debug(f"proxy config: {path} -> {proxy_to}")
            # proxy_to has the form <container>:<port>
            proxy_to_svc, proxy_to_port = proxy_to.split(":")
            rule = {
                "matches": [{"path": {"type": "PathPrefix", "value": path}}],
                "backendRefs": [{"name": proxy_to_svc, "port": int(proxy_to_port)}],
            }
            if path != "/":
                # A sub-path route proxies to the backend's root, matching the
                # rewrite-target behavior of the Ingress arrangement.
                rule["filters"] = [
                    {
                        "type": "URLRewrite",
                        "urlRewrite": {"path": {"type": "ReplacePrefixMatch", "replacePrefixMatch": "/"}},
                    }
                ]
            rules.append(rule)

        return {
            "apiVersion": f"{gateway.GATEWAY_API_GROUP}/{gateway.GATEWAY_API_VERSION}",
            "kind": "HTTPRoute",
            "metadata": {"name": gateway.HTTP_ROUTE_NAME},
            "spec": {
                "parentRefs": [
                    {
                        "kind": "Gateway",
                        "name": gateway_name,
                        "namespace": gateway_namespace,
                    }
                ],
                "hostnames": [host_name],
                "rules": rules,
            },
        }

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
                            name=service_name,
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
        # Volumes the stack author marked `@stack backup-exclude`.  K8up backs up
        # every PVC in the namespace, so the exclusion has to travel with the
        # claim as its own opt-out annotation.
        backup_exclude = set(self.spec.get_backup().get("exclude", []))
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
            annotations = {k8up.BACKUP_ANNOTATION: "false"} if volume_name in backup_exclude else None
            pvc = client.V1PersistentVolumeClaim(
                metadata=client.V1ObjectMeta(name=volume_name, labels=labels, annotations=annotations),
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
                    name=cfg_map_name,
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

            # A remote cluster binds the spec's path on one of its own nodes, so
            # only an absolute path means anything there. A kind deployment binds
            # the path named below instead, which is derived from the volume name
            # and not from the spec at all -- the spec's path only has to locate
            # the data on this machine, and is resolved against the deployment
            # directory when the node's mount is generated (_make_absolute_host_path).
            if not self.spec.is_kind_deployment() and not os.path.isabs(volume_path):
                log_warn(f"WARN: {volume_name}:{volume_path} is not absolute, cannot bind volume.")
                continue

            resources = self.spec.get_volume_resources(volume_name)
            if not resources:
                resources = DEFAULT_VOLUME_RESOURCES

            affinity = self.spec.get_volume_affinity(volume_name)
            source_args = {}
            if self.spec.is_kind_deployment():
                source_args["host_path"] = client.V1HostPathVolumeSource(path=get_kind_pv_bind_mount_path(volume_name))
            elif affinity:
                # A volume that names its node(s) is a `local` volume rather than
                # a hostPath one: the affinity rides on the PersistentVolume, so
                # the scheduler places any pod mounting the claim onto a matching
                # node, instead of the pod landing anywhere and finding the path
                # empty.  Naming one node is the kubernetes.io/hostname label.
                source_args["local"] = client.V1LocalVolumeSource(path=volume_path)
                source_args["node_affinity"] = client.V1VolumeNodeAffinity(
                    required=client.V1NodeSelector(
                        node_selector_terms=[
                            client.V1NodeSelectorTerm(
                                match_expressions=[
                                    client.V1NodeSelectorRequirement(
                                        key=affinity["label"], operator="In", values=[str(affinity["value"])]
                                    )
                                ]
                            )
                        ]
                    )
                )
            else:
                source_args["host_path"] = client.V1HostPathVolumeSource(path=volume_path)
            spec = client.V1PersistentVolumeSpec(
                storage_class_name="manual",
                access_modes=["ReadWriteOnce"],
                capacity=to_k8s_resource_requirements(resources).requests,
                **source_args,
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

                # Env sources are layered in compose precedence order: the deployment-wide
                # config first, then each env_file in the order listed, then the inline
                # environment block.  Later sources override earlier ones, matching what
                # docker compose gives the same pod file.
                merged_envs = self.environment_variables.map.copy()
                if "env_file" in service_info:
                    for env_file in service_info["env_file"]:
                        env_file = f"{pod_dir}/{env_file}"
                        env_vars_from_file = env_var_map_from_file(env_file, expand=False)
                        merged_envs = merge_envs(merged_envs, envs_from_compose_file(env_vars_from_file, merged_envs))

                if "environment" in service_info:
                    merged_envs = merge_envs(merged_envs, envs_from_compose_file(service_info["environment"], merged_envs))

                envs = envs_from_environment_variables_map(merged_envs)

                # Keys the spec declares secret are delivered from the deployment's
                # k8s Secret (created at up time, see K8sDeployer._create_secrets)
                # rather than as literal values, so they never appear in the
                # Deployment object.  Any literal of the same name is dropped: the
                # declaration wins over a leftover default in a compose file.
                secret_names = list(self.spec.get_secrets())
                if secret_names:
                    envs = [env for env in envs if env.name not in secret_names]
                    for secret_name in secret_names:
                        envs.append(
                            client.V1EnvVar(
                                name=secret_name,
                                value_from=client.V1EnvVarSource(
                                    secret_key_ref=client.V1SecretKeySelector(name=K8S_SECRET_NAME, key=secret_name)
                                ),
                            )
                        )
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

                # Re-write the image reference for remote deployment.
                # A kind cluster with no staging registry gets local images loaded
                # directly into it, so the local reference is the right one there.
                # Note self.app_name has the same value as deployment_id
                if self.spec.get_image_registry() is None and self.spec.is_kind_deployment():
                    image_to_use = image
                else:
                    image_to_use = resolve_image_for_deployment(image, self.spec.get_image_registry(), self.app_name)
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

                # A service the stack author gave a `@stack backup-command` gets K8up's
                # dump annotations on its pod, so backups capture a consistent logical
                # dump alongside (or instead of) the raw files.  See docs/backup.md.
                backup_command_info = self.spec.get_backup().get("commands", {}).get(service_name)
                if backup_command_info:
                    if annotations is None:
                        annotations = {}
                    annotations[k8up.BACKUP_COMMAND_ANNOTATION] = backup_command_info["command"]
                    # Defaulted rather than omitted when the stack names no extension, so
                    # that the dump snapshot is named the same here as on the other
                    # target, which defaults it too.
                    extension = backup_command_info.get("file-extension") or constants.backup_default_file_extension
                    annotations[k8up.FILE_EXTENSION_ANNOTATION] = "." + str(extension).lstrip(".")

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

                # Unset unless the spec asks for one, which leaves the cluster's default
                # runtime in place.  A named class must exist on the cluster: k8s rejects
                # a pod naming one that does not, rather than falling back.
                runtime_class_name = self.spec.get_runtime_class(service_name)

                template = client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(annotations=annotations, labels=labels),
                    spec=client.V1PodSpec(
                        containers=[container],
                        image_pull_secrets=image_pull_secrets,
                        volumes=volumes,
                        affinity=affinity,
                        tolerations=tolerations,
                        host_aliases=[localhost_aliases],
                        runtime_class_name=runtime_class_name,
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
                    metadata=client.V1ObjectMeta(name=f"deploy-{service_name}"),
                    spec=spec,
                )

                deployments.append(deployment)

        return deployments
