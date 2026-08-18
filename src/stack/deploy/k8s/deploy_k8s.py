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
import base64
import sys

from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException
from kubernetes.stream import stream
from kubernetes import watch

from stack import constants
from stack.deploy.deployer import ClusterNotRunningException, Deployer, DeployerConfigGenerator
from stack.deploy.k8s.helpers import (
    create_cluster,
    destroy_cluster,
    load_images_into_kind,
)
from stack.deploy.k8s.helpers import install_ingress_for_kind, wait_for_ingress_in_kind
from stack.deploy.k8s.helpers import (
    live_pods,
    pods_in_deployment,
    containers_in_pod,
    log_stream_from_string,
)
from stack.deploy.k8s.helpers import generate_kind_config
from stack.deploy.k8s import gateway
from stack.deploy.k8s import k8up
from stack.deploy.kube_config import kube_config_file
from stack.deploy import secrets as stack_secrets
from stack.deploy.images import is_staged_reference, stale_staged_images
from stack.deploy.backup import backup_settings
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


def _pod_status(pod):
    # A pod enters the Running phase as soon as its containers have started,
    # which is well before the application inside them is able to serve. Only
    # report Running once every container also passes its readiness probe, so
    # that "Running" means the same thing here as a ready pod does to k8s.
    phase = pod.status.phase
    if phase != "Running":
        return phase

    container_statuses = pod.status.container_statuses or []
    total = len(container_statuses)
    ready = len([c for c in container_statuses if c.ready])
    if not total or ready < total:
        return f"Starting {ready}/{total} ready"
    return f"Running {ready}/{total} ready"


def _requested_storage(pvc):
    # A claim that has not bound yet has no capacity, so fall back to what it
    # asked for -- with "?" as the last resort, matching the ingress fields.
    requests = (pvc.spec.resources.requests or {}) if pvc.spec.resources else {}
    return requests.get("storage", "?")


def _node_affinity_summary(pv):
    """The node terms a PV is pinned to, rendered the way `kubectl describe` does."""
    required = pv.spec.node_affinity.required if pv.spec.node_affinity else None
    if not required:
        return None
    terms = []
    for term in required.node_selector_terms or []:
        for expr in term.match_expressions or []:
            values = ",".join(expr.values or [])
            terms.append(f"{expr.key} {expr.operator} [{values}]")
    return "; ".join(terms) if terms else None


def _pv_source(pv):
    """Where on the node (or elsewhere) a PV's bytes live.

    Only the sources stack itself creates -- hostPath, and the `local` volumes
    the common provisioners hand out -- get a path; anything else is named by
    its type, which is still more than the claim says.
    """
    spec = pv.spec
    if spec.host_path:
        return f"hostPath {spec.host_path.path}"
    if spec.local:
        return f"local {spec.local.path}"
    if spec.nfs:
        return f"nfs {spec.nfs.server}:{spec.nfs.path}"
    if spec.csi:
        return f"csi {spec.csi.driver}"
    return None


def _pv_detail_lines(core_api, pvc):
    volume_name = pvc.spec.volume_name
    if not volume_name:
        # Unbound: the storage class is all there is to say about where it will land.
        return [f"StorageClass: {pvc.spec.storage_class_name}"] if pvc.spec.storage_class_name else []

    lines = [f"PersistentVolume: {volume_name}"]
    try:
        pv = core_api.read_persistent_volume(name=volume_name)
    except client.exceptions.ApiException as e:
        # PVs are cluster-scoped, so this is the one part of the report a
        # namespace-scoped credential can be refused.
        log_debug(f"Unable to read PV {volume_name}: {e}")
        return lines

    if pv.spec.storage_class_name:
        lines.append(f"StorageClass: {pv.spec.storage_class_name}")
    source = _pv_source(pv)
    if source:
        lines.append(f"Source: {source}")
    node = (pv.metadata.annotations or {}).get("local.path.provisioner/selected-node")
    if node:
        lines.append(f"Node: {node}")
    affinity = _node_affinity_summary(pv)
    if affinity:
        lines.append(f"Node affinity: {affinity}")
    if pv.spec.persistent_volume_reclaim_policy:
        lines.append(f"Reclaim policy: {pv.spec.persistent_volume_reclaim_policy}")
    return lines


def _canonical_quantity(quantity):
    # Resource quantities are compared by value because the API server
    # canonicalizes what it stores ("1000m" comes back as "1", "1024Mi" as
    # "1Gi"), so comparing the strings we generate against a live object
    # reports phantom changes.
    if quantity is None:
        return None
    text = str(quantity)
    suffixes = {
        "n": 1e-9, "u": 1e-6, "m": 1e-3,
        "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12, "P": 1e15, "E": 1e18,
        "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "Pi": 2**50, "Ei": 2**60,
    }
    for suffix in sorted(suffixes, key=len, reverse=True):
        if text.endswith(suffix):
            return float(text[: -len(suffix)]) * suffixes[suffix]
    return float(text)


def _env_by_name(container):
    # A value_from entry (a secret reference) has no literal value; both kinds
    # are compared, since a var moving between literal and secret-ref is a
    # change the pods have to be rolled to see.
    env = {}
    for var in container.env or []:
        env[var.name] = (var.value, var.value_from.to_dict() if var.value_from else None)
    return env


def _structural_shape(deployment):
    """The parts of a Deployment that update refuses to change, in comparable form.

    Only the fields stack generates are compared, normalized, because a literal
    comparison of a desired object against a live one drowns in server-side
    defaulting (protocol: TCP, canonicalized quantities, injected fields).
    """
    template_spec = deployment.spec.template.spec
    containers = {}
    for c in template_spec.containers:
        resources = c.resources
        containers[c.name] = {
            "ports": sorted((p.container_port, p.protocol or "TCP") for p in (c.ports or [])),
            "volume-mounts": sorted((m.name, m.mount_path, m.sub_path) for m in (c.volume_mounts or [])),
            "requests": {k: _canonical_quantity(v) for k, v in ((resources.requests if resources else None) or {}).items()},
            "limits": {k: _canonical_quantity(v) for k, v in ((resources.limits if resources else None) or {}).items()},
        }
    return {
        "replicas": deployment.spec.replicas,
        "containers": containers,
        "volumes": sorted(v.name for v in (template_spec.volumes or [])),
    }


class K8sDeployer(Deployer):
    name: str = "k8s"
    type: str
    core_api: client.CoreV1Api
    apps_api: client.AppsV1Api
    networking_api: client.NetworkingV1Api
    k8s_namespace: str
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
        self.k8s_namespace = compose_project_name
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
            # Stopping a kind deployment deletes its cluster, and kind removes the
            # context with it, so there is nothing to load once one is stopped.
            # Raised as a condition of its own rather than let the kubernetes
            # client's ConfigException out: to the caller this is "not running",
            # and asking a stopped deployment what it is running is a fair
            # question, not an error.
            context = f"kind-{self.kind_cluster_name}"
            try:
                config.load_kube_config(context=context)
            except ConfigException as e:
                raise ClusterNotRunningException(f"no kind cluster {self.kind_cluster_name} (no kube context {context})") from e
        else:
            # Where the credential comes from is the spec's business, not ours: it
            # may be a file in the deployment directory, or it may be resolved
            # from the environment or a secret store for the length of this call.
            with kube_config_file(self.deployment_context.spec, self.deployment_dir) as kube_config_path:
                config.load_kube_config(config_file=kube_config_path.as_posix())
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

    def _backup_settings(self):
        """This deployment's backup settings, or None if backup is switched off.

        Fails rather than deploying a half-configured backup: a deployment that
        believes it is being backed up and is not is the one outcome worth
        refusing outright.
        """
        settings = backup_settings()
        if not settings.enabled:
            return None
        missing = settings.missing_settings()
        if missing:
            error_exit(f"Error: backup is enabled but these settings are not configured: {', '.join(missing)}")
        if not opts.o.dry_run and not k8up.k8up_available(self.custom_obj_api):
            error_exit(
                "Error: backup is enabled but K8up is not installed on this cluster. "
                "K8up runs the backups; stack only configures them."
            )
        return settings

    def _create_backup_configuration(self):
        settings = self._backup_settings()
        if not settings or opts.o.dry_run:
            return
        k8up.ensure_backup_configured(self.core_api, self.custom_obj_api, self.k8s_namespace, settings)

    def _create_secrets(self):
        """Create or refresh the namespaced Secret the containers' env refers to.

        Generated values are create-or-keep, never rotate: a generated password
        is typically baked into a data volume, so it has to live exactly as long
        as the data does.  On a remote cluster both live in the cluster, so the
        existing Secret is the store.  On kind the data lives under the
        deployment directory and the cluster is destroyed on stop, so generated
        values persist beside the data in secrets.env and the Secret is rebuilt
        from them.  Referenced values are resolved fresh on every up.

        Returns True when the Secret was created or its data changed, so update
        knows the pods have to be restarted to see the new values.
        """
        spec = self.cluster_info.spec
        if not spec.get_secrets() or opts.o.dry_run:
            return False
        existing = None
        try:
            existing_secret = self.core_api.read_namespaced_secret(
                name=stack_secrets.K8S_SECRET_NAME, namespace=self.k8s_namespace
            )
            existing = {k: base64.b64decode(v).decode() for k, v in (existing_secret.data or {}).items()}
        except client.exceptions.ApiException as e:
            if e.status != 404:
                raise
        if self.is_kind():
            values = dict(stack_secrets.ensure_generated_secrets(spec, self.deployment_dir))
        else:
            values = {
                name: (existing or {}).get(name) or stack_secrets.new_secret_value()
                for name in stack_secrets.generated_names(spec)
            }
        values.update(stack_secrets.resolve_referenced_secrets(spec))
        if values == existing:
            log_debug(f"Secret {stack_secrets.K8S_SECRET_NAME} unchanged")
            return False
        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(name=stack_secrets.K8S_SECRET_NAME, namespace=self.k8s_namespace),
            string_data=values,
        )
        try:
            self.core_api.create_namespaced_secret(namespace=self.k8s_namespace, body=secret)
            log_debug(f"Secret {stack_secrets.K8S_SECRET_NAME} created")
        except client.exceptions.ApiException as e:
            if e.status != 409:
                raise
            self.core_api.replace_namespaced_secret(
                name=stack_secrets.K8S_SECRET_NAME, namespace=self.k8s_namespace, body=secret
            )
            log_debug(f"Secret {stack_secrets.K8S_SECRET_NAME} replaced")
        return True

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

    def _create_gateway_resources(self, http_proxy_info_list):
        # TODO: handle multiple definitions
        http_proxy_info = http_proxy_info_list[0]
        host_name = http_proxy_info[constants.host_name_key]
        cluster_issuer = http_proxy_info.get(constants.cluster_issuer_key, gateway.DEFAULT_CLUSTER_ISSUER)
        gw = gateway.ensure_gateway(self.custom_obj_api, cluster_issuer)
        # Note: at present we don't support tls for kind (and enabling tls causes errors)
        if not self.is_kind():
            listener = gateway.https_listener_covering_host(gw, host_name)
            if listener:
                # Already served, e.g. by a machine-provisioned wildcard
                # listener whose certificate covers every host under a domain.
                log_debug(f"Host {host_name} already covered by Gateway listener {listener['name']}")
            else:
                # cert-manager sees the new listener on the annotated Gateway
                # and obtains its certificate over HTTP-01.
                gateway.add_https_listener(self.custom_obj_api, gw, self.k8s_namespace, host_name)

        http_route = self.cluster_info.get_http_route(gateway.GATEWAY_NAME, gateway.GATEWAY_NAMESPACE)
        log_debug(f"Sending this HTTPRoute: {http_route}")
        gateway.create_http_route(self.custom_obj_api, self.k8s_namespace, http_route)

    def up(self, detach, skip_cluster_management, services):
        try:
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

            if not opts.o.dry_run:
                namespace = client.V1Namespace(
                    metadata=client.V1ObjectMeta(name=self.k8s_namespace)
                )
                try:
                    self.core_api.create_namespace(body=namespace)
                    log_debug(f"Namespace {self.k8s_namespace} created")
                except client.exceptions.ApiException as e:
                    if e.status == 409:
                        log_debug(f"Namespace {self.k8s_namespace} already exists")
                    else:
                        raise

            self._create_volume_data()
            self._create_backup_configuration()
            self._create_secrets()
            self._create_deployments()

            http_proxy_info = self.cluster_info.spec.get_http_proxy()
            if http_proxy_info and not opts.o.dry_run and gateway.gateway_api_available(self.custom_obj_api):
                # A Gateway API cluster: routing via an HTTPRoute on the shared
                # Gateway, HTTPS via a per-deployment listener on it.
                self._create_gateway_resources(http_proxy_info)
                return

            # Note: at present we don't support tls for kind (and enabling tls causes errors)
            use_tls = http_proxy_info and not self.is_kind()
            certificate = self._find_certificate_for_host_name(http_proxy_info[0]["host-name"]) if use_tls else None
            if certificate:
                log_debug(f"Using existing certificate: {certificate}")

            ingress: client.V1Ingress = self.cluster_info.get_ingress(use_tls=use_tls, certificate=certificate)
            if ingress:
                log_debug(f"Sending this ingress: {ingress}")
                if not opts.o.dry_run:
                    # We've seen this exception thrown here: kubernetes.client.exceptions.ApiException: (500)
                    ingress_resp = self.networking_api.create_namespaced_ingress(namespace=self.k8s_namespace, body=ingress)
                    log_debug("Ingress created:")
                    log_debug(f"{ingress_resp}")
            else:
                log_debug("No ingress configured")
        except Exception as e:
            error_exit(f"Exception thrown bringing stack up: {e}")

    def down(self, timeout, volumes, skip_cluster_management):  # noqa: C901
        try:
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
                    cfg_map_resp = self.core_api.delete_namespaced_config_map(
                        name=cfg_map.metadata.name,
                        namespace=self.k8s_namespace
                        )
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

            # Only the scheduling stops; the repository the backups are in is
            # deliberately left alone, since backups exist to outlive the
            # deployment that made them.
            if backup_settings().enabled and k8up.k8up_available(self.custom_obj_api):
                k8up.delete_backup_configuration(self.core_api, self.custom_obj_api, self.k8s_namespace)

            if self.cluster_info.spec.get_http_proxy() and gateway.gateway_api_available(self.custom_obj_api):
                gateway.delete_http_route(self.custom_obj_api, self.k8s_namespace)
                # The certificate Secret survives so that a redeployment of the
                # same hostname reuses it rather than asking for a new one.
                gateway.remove_https_listener(self.custom_obj_api, self.k8s_namespace)
            else:
                ingress: client.V1Ingress = self.cluster_info.get_ingress(use_tls=not self.is_kind())
                if ingress:
                    log_debug(f"Deleting this ingress: {ingress}")
                    try:
                        self.networking_api.delete_namespaced_ingress(name=ingress.metadata.name, namespace=self.k8s_namespace)
                    except client.exceptions.ApiException as e:
                        _check_delete_exception(e)
                else:
                    log_debug("No ingress to delete")

            if volumes:
                try:
                    self.core_api.delete_namespace(name=self.k8s_namespace)
                    log_debug(f"Namespace {self.k8s_namespace} deleted")
                except client.exceptions.ApiException as e:
                    _check_delete_exception(e)

            if self.is_kind() and not self.skip_cluster_management:
                # Destroy the kind cluster
                destroy_cluster(self.kind_cluster_name)

        except Exception as e:
            error_exit(f"Exception thrown bringing stack up: {e}")

    def status(self):
        try:
            self.connect_api()
        except ClusterNotRunningException as e:
            log_debug(f"{e}: nothing is running")
            return
        # Call whatever API we need to get the running container list
        pod_response = self.core_api.list_namespaced_pod(
            namespace=self.k8s_namespace,
            label_selector=f"app={self.cluster_info.app_name}",
            watch=False,
        )
        pods = live_pods(pod_response.items) if pod_response.items else []

        if not pods:
            return

        hostname = "?"
        ip = "?"
        tls = "?"
        try:
            if gateway.gateway_api_available(self.custom_obj_api):
                http_route = self.custom_obj_api.get_namespaced_custom_object(
                    group=gateway.GATEWAY_API_GROUP,
                    version=gateway.GATEWAY_API_VERSION,
                    namespace=self.k8s_namespace,
                    plural="httproutes",
                    name=gateway.HTTP_ROUTE_NAME,
                )
                hostname = http_route["spec"]["hostnames"][0]
                gw = gateway.get_gateway(self.custom_obj_api)
                addresses = gw.get("status", {}).get("addresses", [])
                if addresses:
                    ip = addresses[0].get("value", "?")
                listener = gateway.https_listener_covering_host(gw, hostname)
                if listener:
                    # cert-manager names the Certificate after the secret the
                    # listener references.
                    cert = self.custom_obj_api.get_namespaced_custom_object(
                        group="cert-manager.io",
                        version="v1",
                        namespace=gateway.GATEWAY_NAMESPACE,
                        plural="certificates",
                        name=listener["tls"]["certificateRefs"][0]["name"],
                    )
                    tls = "notBefore: %s; notAfter: %s; names: %s" % (
                        cert["status"]["notBefore"],
                        cert["status"]["notAfter"],
                        cert["spec"]["dnsNames"],
                    )
            else:
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
                output_main(f"\t{p.metadata.namespace}/{p.metadata.name}: {_pod_status(p)} ({p.metadata.creation_timestamp})")

        self._output_volume_status()

    def _output_volume_status(self):
        """Report where each of the deployment's volumes actually keeps its data.

        Read from the cluster rather than from the spec, because for the common
        case -- an unmapped volume, left to the storage class -- the spec does
        not know: which node the bytes landed on and the path they landed at are
        decided by the provisioner at bind time, and are exactly what someone
        looking for the data needs.
        """
        try:
            pvc_response = self.core_api.list_namespaced_persistent_volume_claim(
                namespace=self.k8s_namespace,
                label_selector=f"app={self.cluster_info.app_name}",
                watch=False,
            )
        except client.exceptions.ApiException as e:
            log_debug(f"Unable to list PVCs: {e}")
            return

        pvcs = pvc_response.items
        if not pvcs:
            return

        output_main("")
        output_main("Volumes:")
        for pvc in sorted(pvcs, key=lambda p: p.metadata.name):
            capacity = (pvc.status.capacity or {}).get("storage") or _requested_storage(pvc)
            output_main(f"\t{pvc.metadata.name}: {pvc.status.phase} ({capacity})")
            for line in _pv_detail_lines(self.core_api, pvc):
                output_main(f"\t\t{line}")

    def ps(self):
        try:
            self.connect_api()
        except ClusterNotRunningException as e:
            log_debug(f"{e}: nothing is running")
            return []
        pod_response = self.core_api.list_namespaced_pod(
            namespace=self.k8s_namespace,
            label_selector=f"app={self.cluster_info.app_name}",
            watch=False,
        )

        ret = []

        for p in live_pods(pod_response.items):
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
        pods = pods_in_deployment(self.core_api, self.cluster_info.app_name, self.k8s_namespace)
        k8s_pod_name = None
        for pod in pods:
            if f"deploy-{service_name}" in pod:
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

    def _connect_for_backup(self):
        self.connect_api()
        settings = self._backup_settings()
        if not settings:
            error_exit("Error: backup is not enabled (set the 'backup' setting or STACK_BACKUP)")
        return settings

    def backup_now(self):
        settings = self._connect_for_backup()
        k8up.run_backup(self.custom_obj_api, self.k8s_namespace, settings)

    def backup_list(self):
        self._connect_for_backup()
        return k8up.list_snapshots(self.custom_obj_api, self.k8s_namespace)

    def _restorable_volumes(self):
        """The deployment's volumes a restore should fill, in spec order."""
        exclude = set(self.cluster_info.spec.get_backup().get("exclude", []))
        return [name for name in self.cluster_info.spec.get_volumes() if name not in exclude]

    def backup_restore(self, snapshot, volumes, source=None):
        settings = self._connect_for_backup()
        # K8up restores one claim at a time, so a restore is one Restore per
        # volume, each picking the newest snapshot of that volume for itself.
        #
        # Which volumes comes from this deployment rather than from the
        # repository: what is being asked for is "fill my volumes from that
        # backup", and when the backup is another deployment's there is no way to
        # enumerate it from here anyway.
        named = bool(volumes)
        volumes = volumes or self._restorable_volumes()
        if not volumes:
            error_exit("Error: this deployment has no volumes to restore")

        failed = []
        for volume in volumes:
            try:
                k8up.run_restore(self.custom_obj_api, self.k8s_namespace, settings, volume, snapshot, source)
            except k8up.K8upException as e:
                # A volume the backup does not hold is expected when the set of
                # volumes was inferred -- one added since the backup was taken, or
                # a backup from a stack that never had it. Say so and carry on, so
                # that one absent volume does not abandon the rest half restored.
                # A volume the caller named is a different matter: they asked for
                # that one specifically, so its failure is the answer.
                if named:
                    raise
                log_warn(f"WARN: could not restore {volume}: {e}")
                failed.append(volume)

        if len(failed) == len(volumes):
            error_exit(f"Error: nothing could be restored from {source or 'this deployment'}: {failed[-1]}")

    def logs(self, services, tail, follow, stream):
        self.connect_api()
        pods = pods_in_deployment(self.core_api, self.cluster_info.app_name, self.k8s_namespace)
        if len(pods) == 0:
            log_data = "******* Pods not running ********\n"

        if services:
            matched_pods = []
            for svc in services:
                for pod in pods:
                    if f"deploy-{svc}" in pod:
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
                containers = containers_in_pod(self.core_api, k8s_pod_name, self.k8s_namespace)
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
                containers = containers_in_pod(self.core_api, k8s_pod_name, self.k8s_namespace)
                # If the pod is not yet started, the logs request below will throw an exception
                try:
                    log_data = ""
                    for container in containers:
                        container_log = self.core_api.read_namespaced_pod_log(
                            k8s_pod_name, namespace=self.k8s_namespace, container=container, tail_lines=tail
                        )
                        # A container that is running but has not written anything yet
                        # returns an empty body, which the client deserializes to None
                        # rather than "". Common against a real cluster, where a caller
                        # polling for a log line reaches a container whose image has only
                        # just finished being pulled.
                        container_log_lines = (container_log or "").splitlines()
                        for line in container_log_lines:
                            log_data += f"{container}: {line}\n"
                except client.exceptions.ApiException as e:
                    log_debug(f"Error from read_namespaced_pod_log: {e}")
                    log_data = "******* No logs available ********\n"
                all_logs.append(log_data)
            return log_stream_from_string("\n".join(all_logs))

    def update(self):
        """Converge the running deployment on its deployment directory.

        The updatable surface is deliberately content only: image references,
        environment, and secret values.  Anything structural -- services,
        ports, volumes, resources, replicas -- is refused with a redeploy
        message rather than half-applied, so the whole diff of desired against
        live is computed before anything is written.
        """
        self.connect_api()
        spec = self.cluster_info.spec
        deployment_id = self.cluster_info.app_name
        desired_deployments = self.cluster_info.get_deployments(image_pull_policy=None if self.is_kind() else "Always")

        live_deployments = {
            d.metadata.name: d for d in self.apps_api.list_namespaced_deployment(namespace=self.k8s_namespace).items
        }
        if not live_deployments:
            raise ClusterNotRunningException(f"no deployments found in namespace {self.k8s_namespace}")

        desired_names = {d.metadata.name for d in desired_deployments}
        structural = [f"{name}: service added" for name in sorted(desired_names - set(live_deployments))]
        structural += [f"{name}: service removed" for name in sorted(set(live_deployments) - desired_names)]
        for desired in desired_deployments:
            live = live_deployments.get(desired.metadata.name)
            if live is None:
                continue
            desired_shape, live_shape = _structural_shape(desired), _structural_shape(live)
            if desired_shape != live_shape:
                changed = sorted(k for k in desired_shape if desired_shape[k] != live_shape[k])
                structural.append(f"{desired.metadata.name}: {', '.join(changed)} changed")
        if structural:
            detail = "\n".join(f"  {line}" for line in structural)
            error_exit(
                "update only applies image, environment and secret changes, but the deployment's"
                f" shape has changed:\n{detail}\nRe-create the deployment to apply these."
            )

        stale_refs = set()
        kind_images_reloaded = False
        if self.is_kind() and spec.get_image_registry() is None:
            # The cluster runs the images loaded into it, so converging on the
            # current builds means loading them again.  Whether any content
            # actually changed is not visible from here, so the pods are
            # restarted regardless.
            log_info("Loading current local images into the kind cluster...")
            load_images_into_kind(self.kind_cluster_name, self.cluster_info.image_set)
            kind_images_reloaded = True
        else:
            for source, staged in stale_staged_images(self.cluster_info.image_set, spec.get_image_registry(), deployment_id):
                stale_refs.add(staged)
                log_warn(
                    f"The local build of {source} is newer than the staged image: run"
                    f" 'stack manage --dir {self.deployment_dir} push-images' and update again to deploy it."
                )

        # Referenced secrets may have rotated, and a deployment created before
        # its stack declared secrets has no Secret yet.
        secrets_changed = self._create_secrets()
        if secrets_changed:
            output_main("secrets: changed; restarting all services")

        for desired in desired_deployments:
            name = desired.metadata.name
            desired_containers = {c.name: c for c in desired.spec.template.spec.containers}

            def converge(live):
                changes = []
                restart = kind_images_reloaded or secrets_changed
                for container in live.spec.template.spec.containers:
                    desired_container = desired_containers[container.name]
                    if container.image != desired_container.image:
                        changes.append(f"image {container.image} -> {desired_container.image}")
                        container.image = desired_container.image
                    elif is_staged_reference(desired_container.image, deployment_id) and desired_container.image not in stale_refs:
                        # New content under this deployment's mutable staging tag
                        # arrives with the reference unchanged, so picking it up
                        # means a restart and a re-pull rather than a spec change.
                        changes.append(f"re-pulling staged image {desired_container.image}")
                        restart = True
                    live_env, desired_env = _env_by_name(container), _env_by_name(desired_container)
                    env_changed = sorted(k for k in set(live_env) | set(desired_env) if live_env.get(k) != desired_env.get(k))
                    if env_changed:
                        changes.append(f"env changed ({', '.join(env_changed)})")
                        container.env = desired_container.env
                if restart:
                    # Merged, not assigned: the pod template also carries the K8up
                    # backup-command annotations, which a restart must not strip.
                    annotations = live.spec.template.metadata.annotations or {}
                    annotations["kubectl.kubernetes.io/restartedAt"] = (
                        datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()
                    )
                    live.spec.template.metadata.annotations = annotations
                return changes, restart

            live = live_deployments[name]
            changes, force_restart = converge(live)
            if not changes and not force_restart:
                output_main(f"{name}: unchanged")
                continue
            for change in changes:
                output_main(f"{name}: {change}")
            if force_restart and not changes and not secrets_changed:
                output_main(f"{name}: restarting")

            # The patch sends back the object read at the top of update(), whose
            # resourceVersion is by now stale: on kind the image reload sits
            # between that read and here, and each earlier patch in this loop
            # sets off a rollout.  Anything touching the Deployment meanwhile --
            # the controller updating status is enough -- makes this write a
            # 409, so a conflict is re-read and re-applied rather than raised:
            # what is being requested is content convergence, which a fresh
            # read expresses just as well.
            for attempt in range(3):
                try:
                    self.apps_api.patch_namespaced_deployment(
                        name=name,
                        namespace=self.k8s_namespace,
                        body=live,
                    )
                    break
                except client.exceptions.ApiException as e:
                    if e.status != 409 or attempt == 2:
                        raise
                    log_debug(f"{name}: patch conflicted, re-reading and retrying")
                    live = self.apps_api.read_namespaced_deployment(name=name, namespace=self.k8s_namespace)
                    converge(live)

    def read_secrets(self):
        spec = self.cluster_info.spec
        secret_entries = spec.get_secrets()
        if not secret_entries:
            return {}
        # The store is where the data lives (see _create_secrets): on kind that
        # is the deployment directory, which also spares connecting to a cluster
        # that a stopped kind deployment no longer has.
        if self.is_kind():
            return stack_secrets.local_secret_values(spec, self.deployment_dir)
        self.connect_api()
        try:
            secret = self.core_api.read_namespaced_secret(name=stack_secrets.K8S_SECRET_NAME, namespace=self.k8s_namespace)
        except client.exceptions.ApiException as e:
            if e.status != 404:
                raise
            error_exit("no secrets in the cluster yet: they are created when the deployment is first started")
        stored = {k: base64.b64decode(v).decode() for k, v in (secret.data or {}).items()}
        return {name: stored.get(name) for name in secret_entries}

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
            # Generated secrets have to outlive the cluster, which stopping a kind
            # deployment destroys; they persist beside the data, in secrets.env.
            stack_secrets.ensure_generated_secrets(self.deployment_context.spec, deployment_dir)
            # Check the file isn't already there
            # Get the config file contents
            content = generate_kind_config(deployment_dir, self.deployment_context)
            log_debug(f"kind config is: {content}")
            config_file = deployment_dir.joinpath(constants.kind_config_filename)
            # Write the file
            with open(config_file, "w") as output_file:
                output_file.write(content)
