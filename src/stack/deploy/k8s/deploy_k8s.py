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
import sys

from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

from kubernetes import client, config
from kubernetes.stream import stream
from kubernetes import watch

from stack import constants
from stack.deploy.deployer import Deployer, DeployerConfigGenerator
from stack.deploy.k8s.helpers import (
    create_cluster,
    destroy_cluster,
    load_images_into_kind,
)
from stack.deploy.k8s.helpers import install_ingress_for_kind, wait_for_ingress_in_kind
from stack.deploy.k8s.helpers import (
    pods_in_deployment,
    containers_in_pod,
    log_stream_from_string,
)
from stack.deploy.k8s.helpers import generate_kind_config, DEFAULT_K8S_NAMESPACE
from stack.deploy.k8s.cluster_info import ClusterInfo
from stack.opts import opts
from stack.deploy.deployment_context import DeploymentContext
from stack.log import log_debug, log_warn, log_info, output_main
from stack.util import error_exit


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self


def _check_delete_exception(e: client.exceptions.ApiException):
    if e.status == 404:
        log_debug("Failed to delete object, continuing")
    else:
        error_exit(f"k8s api error: {e}")


class K8sDeployer(Deployer):
    name: str = "k8s"
    type: str
    core_api: client.CoreV1Api
    apps_api: client.AppsV1Api
    networking_api: client.NetworkingV1Api
    k8s_namespace: str = DEFAULT_K8S_NAMESPACE
    kind_cluster_name: str
    skip_cluster_management: bool
    cluster_info: ClusterInfo
    deployment_dir: Path
    deployment_context: DeploymentContext

    def __init__(
        self,
        type,
        deployment_context: DeploymentContext,
        compose_files,
        compose_project_name,
        compose_env_file,
    ) -> None:
        self.type = type
        self.skip_cluster_management = False
        # TODO: workaround pending refactoring above to cope with being created with a null deployment_context
        if deployment_context is None:
            return
        self.deployment_dir = deployment_context.deployment_dir
        self.deployment_context = deployment_context
        self.kind_cluster_name = compose_project_name
        self.cluster_info = ClusterInfo()
        self.cluster_info.int(
            compose_files,
            compose_env_file,
            compose_project_name,
            deployment_context.spec,
        )
        log_debug(f"Deployment dir: {deployment_context.deployment_dir}")
        log_debug(f"Compose files: {compose_files}")
        log_debug(f"Project name: {compose_project_name}")
        log_debug(f"Shared Env file: {compose_env_file}")
        log_debug(f"Type: {type}")

    def connect_api(self):
        if self.is_kind():
            config.load_kube_config(context=f"kind-{self.kind_cluster_name}")
        else:
            # Get the config file and pass to load_kube_config()
            config.load_kube_config(config_file=self.deployment_dir.joinpath(constants.kube_config_filename).as_posix())
        self.core_api = client.CoreV1Api()
        self.networking_api = client.NetworkingV1Api()
        self.apps_api = client.AppsV1Api()
        self.custom_obj_api = client.CustomObjectsApi()

    def _create_volume_data(self):
        # Create the host-path-mounted PVs for this deployment
        pvs = self.cluster_info.get_pvs()
        for pv in pvs:
            log_debug(f"Sending this pv: {pv}")
            if not opts.o.dry_run:
                try:
                    pv_resp = self.core_api.read_persistent_volume(name=pv.metadata.name)
                    if pv_resp:
                        log_debug("PVs already present:")
                        log_debug(f"{pv_resp}")
                        continue
                except:  # noqa: E722
                    pass

                pv_resp = self.core_api.create_persistent_volume(body=pv)
                log_debug("PVs created:")
                log_debug(f"{pv_resp}")

        # Figure out the PVCs for this deployment
        pvcs = self.cluster_info.get_pvcs()
        for pvc in pvcs:
            log_debug(f"Sending this pvc: {pvc}")

            if not opts.o.dry_run:
                try:
                    pvc_resp = self.core_api.read_namespaced_persistent_volume_claim(
                        name=pvc.metadata.name, namespace=self.k8s_namespace
                    )
                    if pvc_resp:
                        log_debug("PVCs already present:")
                        log_debug(f"{pvc_resp}")
                        continue
                except:  # noqa: E722
                    pass

                pvc_resp = self.core_api.create_namespaced_persistent_volume_claim(body=pvc, namespace=self.k8s_namespace)
                log_debug("PVCs created:")
                log_debug(f"{pvc_resp}")

        # Figure out the ConfigMaps for this deployment
        config_maps = self.cluster_info.get_configmaps()
        for cfg_map in config_maps:
            log_debug(f"Sending this ConfigMap: {cfg_map}")
            if not opts.o.dry_run:
                cfg_rsp = self.core_api.create_namespaced_config_map(body=cfg_map, namespace=self.k8s_namespace)
                log_debug("ConfigMap created:")
                log_debug(f"{cfg_rsp}")

    def _create_deployments(self):
        # Process compose files into a Deployment
        deployments = self.cluster_info.get_deployments(image_pull_policy=None if self.is_kind() else "Always")
        for deployment in deployments:
            # Create the k8s objects
            log_debug(f"Sending this deployment: {deployment}")
            if not opts.o.dry_run:
                deployment_resp = self.apps_api.create_namespaced_deployment(body=deployment, namespace=self.k8s_namespace)
                log_debug("Deployment created:")
                log_debug(
                    f"{deployment_resp.metadata.namespace} {deployment_resp.metadata.name} \
                    {deployment_resp.metadata.generation} {deployment_resp.spec.template.spec.containers[0].image}"
                )

        services: client.V1Service = self.cluster_info.get_services()
        log_debug(f"Sending these services: {services}")
        if not opts.o.dry_run:
            for svc in services:
                service_resp = self.core_api.create_namespaced_service(namespace=self.k8s_namespace, body=svc)
                log_debug("Service created:")
                log_debug(f"{service_resp}")

    def _find_certificate_for_host_name(self, host_name):
        all_certificates = self.custom_obj_api.list_namespaced_custom_object(
            group="cert-manager.io",
            version="v1",
            namespace=self.k8s_namespace,
            plural="certificates",
        )

        host_parts = host_name.split(".", 1)
        host_as_wild = None
        if len(host_parts) == 2:
            host_as_wild = f"*.{host_parts[1]}"

        # TODO: resolve method deprecation below
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%S%z"

        # Walk over all the configured certificates.
        for cert in all_certificates["items"]:
            dns = cert["spec"]["dnsNames"]
            # Check for an exact hostname match or a wildcard match.
            if host_name in dns or host_as_wild in dns:
                status = cert.get("status", {})
                # Check the certificate date.
                if "notAfter" in status and "notBefore" in status:
                    before = datetime.strptime(status["notBefore"], fmt)
                    after = datetime.strptime(status["notAfter"], fmt)
                    if before < now < after:
                        # Check the status is Ready
                        for condition in status.get("conditions", []):
                            if "True" == condition.get("status") and "Ready" == condition.get("type"):
                                return cert
        return None

    def up(self, detach, skip_cluster_management, services):
        self.skip_cluster_management = skip_cluster_management
        if not opts.o.dry_run:
            if self.is_kind() and not self.skip_cluster_management:
                # Create the kind cluster
                create_cluster(
                    self.kind_cluster_name,
                    self.deployment_dir.joinpath(constants.kind_config_filename),
                )
                # Ensure the referenced containers are copied into kind
                load_images_into_kind(self.kind_cluster_name, self.cluster_info.image_set)
            self.connect_api()
            if self.is_kind() and not self.skip_cluster_management:
                # Now configure an ingress controller (not installed by default in kind)
                install_ingress_for_kind()
                # Wait for ingress to start (deployment provisioning will fail unless this is done)
                wait_for_ingress_in_kind()

        else:
            log_info("Dry run mode enabled, skipping k8s API connect")

        self._create_volume_data()
        self._create_deployments()

        http_proxy_info = self.cluster_info.spec.get_http_proxy()
        # Note: at present we don't support tls for kind (and enabling tls causes errors)
        use_tls = http_proxy_info and not self.is_kind()
        certificate = self._find_certificate_for_host_name(http_proxy_info[0]["host-name"]) if use_tls else None
        if certificate:
            log_debug(f"Using existing certificate: {certificate}")

        ingress: client.V1Ingress = self.cluster_info.get_ingress(use_tls=use_tls, certificate=certificate)
        if ingress:
            log_debug(f"Sending this ingress: {ingress}")
            if not opts.o.dry_run:
                ingress_resp = self.networking_api.create_namespaced_ingress(namespace=self.k8s_namespace, body=ingress)
                log_debug("Ingress created:")
                log_debug(f"{ingress_resp}")
        else:
            log_debug("No ingress configured")

    def down(self, timeout, volumes, skip_cluster_management):  # noqa: C901
        self.skip_cluster_management = skip_cluster_management
        self.connect_api()
        # Delete the k8s objects

        if volumes:
            # Create the host-path-mounted PVs for this deployment
            pvs = self.cluster_info.get_pvs()
            for pv in pvs:
                log_debug(f"Deleting this pv: {pv}")
                try:
                    pv_resp = self.core_api.delete_persistent_volume(name=pv.metadata.name)
                    log_debug("PV deleted:")
                    log_debug(f"{pv_resp}")
                except client.exceptions.ApiException as e:
                    _check_delete_exception(e)

            # Figure out the PVCs for this deployment
            pvcs = self.cluster_info.get_pvcs()
            for pvc in pvcs:
                log_debug(f"Deleting this pvc: {pvc}")
                try:
                    pvc_resp = self.core_api.delete_namespaced_persistent_volume_claim(
                        name=pvc.metadata.name, namespace=self.k8s_namespace
                    )
                    log_debug("PVCs deleted:")
                    log_debug(f"{pvc_resp}")
                except client.exceptions.ApiException as e:
                    _check_delete_exception(e)

        # Figure out the ConfigMaps for this deployment
        cfg_maps = self.cluster_info.get_configmaps()
        for cfg_map in cfg_maps:
            log_debug(f"Deleting this ConfigMap: {cfg_map}")
            try:
                cfg_map_resp = self.core_api.delete_namespaced_config_map(name=cfg_map.metadata.name, namespace=self.k8s_namespace)
                log_debug("ConfigMap deleted:")
                log_debug(f"{cfg_map_resp}")
            except client.exceptions.ApiException as e:
                _check_delete_exception(e)

        deployments = self.cluster_info.get_deployments()
        for deployment in deployments:
            log_debug(f"Deleting this deployment: {deployment}")
            try:
                self.apps_api.delete_namespaced_deployment(name=deployment.metadata.name, namespace=self.k8s_namespace)
            except client.exceptions.ApiException as e:
                _check_delete_exception(e)

        services: client.V1Service = self.cluster_info.get_services()
        for svc in services:
            log_debug(f"Deleting service: {svc}")
            try:
                self.core_api.delete_namespaced_service(namespace=self.k8s_namespace, name=svc.metadata.name)
            except client.exceptions.ApiException as e:
                _check_delete_exception(e)

        ingress: client.V1Ingress = self.cluster_info.get_ingress(use_tls=not self.is_kind())
        if ingress:
            log_debug(f"Deleting this ingress: {ingress}")
            try:
                self.networking_api.delete_namespaced_ingress(name=ingress.metadata.name, namespace=self.k8s_namespace)
            except client.exceptions.ApiException as e:
                _check_delete_exception(e)
        else:
            log_debug("No ingress to delete")

        if self.is_kind() and not self.skip_cluster_management:
            # Destroy the kind cluster
            destroy_cluster(self.kind_cluster_name)

    def status(self):
        self.connect_api()
        # Call whatever API we need to get the running container list
        all_pods = self.core_api.list_pod_for_all_namespaces(watch=False)
        pods = []

        if all_pods.items:
            for p in all_pods.items:
                if f"{self.cluster_info.app_name}-deploy" in p.metadata.name:
                    pods.append(p)

        if not pods:
            return

        hostname = "?"
        ip = "?"
        tls = "?"
        try:
            ingress = self.networking_api.read_namespaced_ingress(
                namespace=self.k8s_namespace,
                name=self.cluster_info.get_ingress().metadata.name,
            )

            cert = self.custom_obj_api.get_namespaced_custom_object(
                group="cert-manager.io",
                version="v1",
                namespace=self.k8s_namespace,
                plural="certificates",
                name=ingress.spec.tls[0].secret_name,
            )

            hostname = ingress.spec.rules[0].host
            ip = ingress.status.load_balancer.ingress[0].ip
            tls = "notBefore: %s; notAfter: %s; names: %s" % (
                cert["status"]["notBefore"],
                cert["status"]["notAfter"],
                ingress.spec.tls[0].hosts,
            )
        except:  # noqa: E722
            pass

        output_main("Ingress:")
        output_main(f"\tHostname: {hostname}")
        output_main(f"\tIP: {ip}")
        output_main(f"\tTLS: {tls}")
        output_main("")
        output_main("Pods:")

        for p in pods:
            if p.metadata.deletion_timestamp:
                output_main(f"\t{p.metadata.namespace}/{p.metadata.name}: Terminating ({p.metadata.deletion_timestamp})")
            else:
                output_main(f"\t{p.metadata.namespace}/{p.metadata.name}: {p.status.phase} ({p.metadata.creation_timestamp})")

    def ps(self):
        self.connect_api()
        pods = self.core_api.list_pod_for_all_namespaces(watch=False)

        ret = []

        for p in pods.items:
            if f"{self.cluster_info.app_name}-deploy" in p.metadata.name:
                pod_ip = p.status.pod_ip
                ports = AttrDict()
                for c in p.spec.containers:
                    if c.ports:
                        for prt in c.ports:
                            ports[str(prt.container_port)] = [AttrDict({"HostIp": pod_ip, "HostPort": prt.container_port})]

                ret.append(
                    AttrDict(
                        {
                            "id": f"{p.metadata.namespace}/{p.metadata.name}",
                            "name": p.metadata.name,
                            "namespace": p.metadata.namespace,
                            "network_settings": AttrDict({"ports": ports}),
                        }
                    )
                )

        return ret

    def port(self, service, private_port):
        # Since we handle the port mapping, need to figure out where this comes from
        # Also look into whether it makes sense to get ports for k8s
        pass

    def execute(self, service_name, command, tty, envs):
        self.connect_api()
        pods = pods_in_deployment(self.core_api, self.cluster_info.app_name)
        k8s_pod_name = None
        for pod in pods:
            if f"{self.cluster_info.app_name}-deploy-{service_name}" in pod:
                k8s_pod_name = pod
                break

        if not k8s_pod_name:
            log_warn("Warning: pod not running")
            return

        response = stream(
            self.core_api.connect_get_namespaced_pod_exec,
            k8s_pod_name,
            container=service_name,
            namespace=self.k8s_namespace,
            command=command,
            tty=False,
            stdin=False,
            stdout=True,
            stderr=True,
            _preload_content=False,
        )
        response.run_forever()
        if response.returncode:
            output_main(response.read_all())
            sys.exit(response.returncode)

        output_main(response.read_stdout())

    def logs(self, services, tail, follow, stream):
        self.connect_api()
        pods = pods_in_deployment(self.core_api, self.cluster_info.app_name)
        if len(pods) == 0:
            log_data = "******* Pods not running ********\n"

        if services:
            matched_pods = []
            for svc in services:
                for pod in pods:
                    if f"{self.cluster_info.app_name}-deploy-{svc}" in pod:
                        matched_pods.append(pod)
            pods = matched_pods

        if follow:

            def log_follower(pod_name, container):
                w = watch.Watch()
                for line in w.stream(
                    self.core_api.read_namespaced_pod_log,
                    name=pod_name,
                    container=container,
                    tail_lines=tail,
                    namespace=self.k8s_namespace,
                ):
                    output_main(f"{container}: {line}")

            threads = []
            for k8s_pod_name in pods:
                containers = containers_in_pod(self.core_api, k8s_pod_name)
                for container in containers:
                    t = Thread(target=log_follower, args=(k8s_pod_name, container), daemon=True)
                    t.start()
                    threads.append(t)
            for t in threads:
                t.join()

            return log_stream_from_string("")
        else:
            all_logs = []
            for k8s_pod_name in pods:
                containers = containers_in_pod(self.core_api, k8s_pod_name)
                # If the pod is not yet started, the logs request below will throw an exception
                try:
                    log_data = ""
                    for container in containers:
                        container_log = self.core_api.read_namespaced_pod_log(
                            k8s_pod_name, namespace=self.k8s_namespace, container=container, tail_lines=tail
                        )
                        container_log_lines = container_log.splitlines()
                        for line in container_log_lines:
                            log_data += f"{container}: {line}\n"
                except client.exceptions.ApiException as e:
                    log_debug(f"Error from read_namespaced_pod_log: {e}")
                    log_data = "******* No logs available ********\n"
                all_logs.append(log_data)
            return log_stream_from_string("\n".join(all_logs))

    def update(self):
        self.connect_api()
        ref_deployments = self.cluster_info.get_deployments()

        for ref_deployment in ref_deployments:
            deployment = self.apps_api.read_namespaced_deployment(name=ref_deployment.metadata.name, namespace=self.k8s_namespace)

            new_env = ref_deployment.spec.template.spec.containers[0].env
            for container in deployment.spec.template.spec.containers:
                old_env = container.env
                if old_env != new_env:
                    container.env = new_env

            deployment.spec.template.metadata.annotations = {
                "kubectl.kubernetes.io/restartedAt": datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
            }

            self.apps_api.patch_namespaced_deployment(
                name=ref_deployment.metadata.name,
                namespace=self.k8s_namespace,
                body=deployment,
            )

    def run(
        self,
        image: str,
        command=None,
        user=None,
        volumes=None,
        entrypoint=None,
        env={},
        ports=[],
        detach=False,
    ):
        # We need to figure out how to do this -- check why we're being called first
        pass

    def is_kind(self):
        return self.type == "k8s-kind"


class K8sDeployerConfigGenerator(DeployerConfigGenerator):
    type: str

    def __init__(self, type: str, deployment_context) -> None:
        self.type = type
        self.deployment_context = deployment_context
        super().__init__()

    def generate(self, deployment_dir: Path):
        # No need to do this for the remote k8s case
        if self.type == "k8s-kind":
            # Check the file isn't already there
            # Get the config file contents
            content = generate_kind_config(deployment_dir, self.deployment_context)
            log_debug(f"kind config is: {content}")
            config_file = deployment_dir.joinpath(constants.kind_config_filename)
            # Write the file
            with open(config_file, "w") as output_file:
                output_file.write(content)
