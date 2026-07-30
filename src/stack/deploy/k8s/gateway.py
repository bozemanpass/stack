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

"""Gateway API support for HTTPS endpoint provisioning.

On clusters provisioned with the Gateway API (rather than the legacy nginx
ingress arrangement), stack serves HTTP traffic through a single shared Gateway
and provisions HTTPS per application: each deployment attaches an HTTPRoute to
the Gateway for routing, and adds an HTTPS listener to the Gateway for its
hostname.  cert-manager watches the Gateway (via its cluster-issuer annotation)
and obtains a certificate for each HTTPS listener over ACME HTTP-01, into the
Secret the listener names.

The Gateway's name and namespace are a contract with the machine provisioning
scripts, which point the ClusterIssuers' HTTP-01 solver at the same Gateway.
stack treats the Gateway as its own: the machine side deliberately does not
manage it through the traefik helm chart (whose re-syncs would drop the
listeners added here), and stack creates it if it does not exist.

A machine may instead be provisioned with a wildcard certificate on a static
HTTPS listener (issued over DNS-01, which needs DNS API access stack cannot
assume).  Deployments whose hostname is already covered by such a listener get
no listener of their own -- only an HTTPRoute.
"""

from kubernetes import client

from stack.log import log_debug

GATEWAY_API_GROUP = "gateway.networking.k8s.io"
GATEWAY_API_VERSION = "v1"

# The contract with the machine provisioning scripts (see stirlingbridge
# machine-provisioning k3s-node.sh --gateway-api).
GATEWAY_NAME = "stack-gateway"
GATEWAY_NAMESPACE = "kube-system"
GATEWAY_CLASS_NAME = "traefik"
DEFAULT_CLUSTER_ISSUER = "letsencrypt-prod"

# traefik's entrypoint ports, which its service exposes as 80 and 443.  A
# listener is only served if its port matches an entrypoint.
GATEWAY_HTTP_PORT = 8000
GATEWAY_HTTPS_PORT = 8443

HTTP_ROUTE_NAME = "http-route"

CLUSTER_ISSUER_ANNOTATION = "cert-manager.io/cluster-issuer"


def gateway_api_available(custom_obj_api: client.CustomObjectsApi) -> bool:
    """True if this cluster serves traffic through the Gateway API contract.

    The check is for the contract GatewayClass rather than just the CRDs: CRDs
    without an implementation behind them cannot serve traffic, and a cluster
    provisioned the legacy way has neither.
    """
    try:
        custom_obj_api.get_cluster_custom_object(
            group=GATEWAY_API_GROUP,
            version=GATEWAY_API_VERSION,
            plural="gatewayclasses",
            name=GATEWAY_CLASS_NAME,
        )
        return True
    except client.exceptions.ApiException as e:
        # 404 covers both a missing GatewayClass and missing CRDs.
        log_debug(f"Gateway API not available ({e.status}), using the Ingress API")
        return False


def get_gateway(custom_obj_api: client.CustomObjectsApi):
    try:
        return custom_obj_api.get_namespaced_custom_object(
            group=GATEWAY_API_GROUP,
            version=GATEWAY_API_VERSION,
            namespace=GATEWAY_NAMESPACE,
            plural="gateways",
            name=GATEWAY_NAME,
        )
    except client.exceptions.ApiException as e:
        if e.status == 404:
            return None
        raise


def _http_listener():
    return {
        "name": "web",
        "port": GATEWAY_HTTP_PORT,
        "protocol": "HTTP",
        "allowedRoutes": {"namespaces": {"from": "All"}},
    }


def ensure_gateway(custom_obj_api: client.CustomObjectsApi, cluster_issuer: str = DEFAULT_CLUSTER_ISSUER):
    """Return the contract Gateway, creating it if it does not exist.

    The machine provisioning script normally creates the Gateway, so this is a
    fallback that makes stack self-sufficient on any cluster that has the
    contract GatewayClass.
    """
    gateway = get_gateway(custom_obj_api)
    if gateway:
        return gateway
    gateway = {
        "apiVersion": f"{GATEWAY_API_GROUP}/{GATEWAY_API_VERSION}",
        "kind": "Gateway",
        "metadata": {
            "name": GATEWAY_NAME,
            "namespace": GATEWAY_NAMESPACE,
            "annotations": {CLUSTER_ISSUER_ANNOTATION: cluster_issuer},
        },
        "spec": {
            "gatewayClassName": GATEWAY_CLASS_NAME,
            "listeners": [_http_listener()],
        },
    }
    log_debug(f"Creating Gateway: {gateway}")
    return custom_obj_api.create_namespaced_custom_object(
        group=GATEWAY_API_GROUP,
        version=GATEWAY_API_VERSION,
        namespace=GATEWAY_NAMESPACE,
        plural="gateways",
        body=gateway,
    )


def hostname_matches(listener_hostname: str, host_name: str) -> bool:
    """True if a listener hostname (possibly a wildcard) covers host_name.

    A wildcard covers exactly one extra label, matching what a wildcard TLS
    certificate covers: *.example.com covers app.example.com but neither
    example.com nor a.b.example.com.
    """
    if not listener_hostname:
        return False
    if listener_hostname == host_name:
        return True
    if listener_hostname.startswith("*."):
        host_parts = host_name.split(".", 1)
        return len(host_parts) == 2 and host_parts[1] == listener_hostname[2:]
    return False


def https_listener_covering_host(gateway, host_name: str):
    """The Gateway's HTTPS listener already serving host_name, or None."""
    for listener in gateway.get("spec", {}).get("listeners", []):
        if listener.get("protocol") == "HTTPS" and hostname_matches(listener.get("hostname"), host_name):
            return listener
    return None


def listener_name_for_deployment(deployment_name: str) -> str:
    return f"{deployment_name}-https"


def secret_name_for_deployment(deployment_name: str) -> str:
    return f"{deployment_name}-tls"


def https_listener_for_deployment(deployment_name: str, host_name: str):
    return {
        "name": listener_name_for_deployment(deployment_name),
        "port": GATEWAY_HTTPS_PORT,
        "protocol": "HTTPS",
        "hostname": host_name,
        "allowedRoutes": {"namespaces": {"from": "All"}},
        "tls": {
            "mode": "Terminate",
            "certificateRefs": [{"name": secret_name_for_deployment(deployment_name)}],
        },
    }


def _patch_listeners(custom_obj_api: client.CustomObjectsApi, listeners):
    # The python client sends merge-patch for custom objects, which replaces
    # the listeners array wholesale -- exactly what is wanted here.
    custom_obj_api.patch_namespaced_custom_object(
        group=GATEWAY_API_GROUP,
        version=GATEWAY_API_VERSION,
        namespace=GATEWAY_NAMESPACE,
        plural="gateways",
        name=GATEWAY_NAME,
        body={"spec": {"listeners": listeners}},
    )


def add_https_listener(custom_obj_api: client.CustomObjectsApi, gateway, deployment_name: str, host_name: str):
    """Add (or update in place) this deployment's HTTPS listener on the Gateway."""
    new_listener = https_listener_for_deployment(deployment_name, host_name)
    listeners = [listener for listener in gateway["spec"]["listeners"] if listener["name"] != new_listener["name"]]
    listeners.append(new_listener)
    log_debug(f"Adding Gateway listener: {new_listener}")
    _patch_listeners(custom_obj_api, listeners)


def remove_https_listener(custom_obj_api: client.CustomObjectsApi, deployment_name: str):
    """Remove this deployment's HTTPS listener from the Gateway, if present.

    The certificate Secret is left behind deliberately: a redeployment of the
    same hostname re-adds the listener and cert-manager reuses the still-valid
    certificate rather than asking Let's Encrypt for a new one.
    """
    gateway = get_gateway(custom_obj_api)
    if not gateway:
        return
    listener_name = listener_name_for_deployment(deployment_name)
    listeners = gateway["spec"]["listeners"]
    remaining = [listener for listener in listeners if listener["name"] != listener_name]
    if len(remaining) != len(listeners):
        log_debug(f"Removing Gateway listener: {listener_name}")
        _patch_listeners(custom_obj_api, remaining)


def create_http_route(custom_obj_api: client.CustomObjectsApi, namespace: str, http_route):
    log_debug(f"Creating HTTPRoute: {http_route}")
    return custom_obj_api.create_namespaced_custom_object(
        group=GATEWAY_API_GROUP,
        version=GATEWAY_API_VERSION,
        namespace=namespace,
        plural="httproutes",
        body=http_route,
    )


def delete_http_route(custom_obj_api: client.CustomObjectsApi, namespace: str):
    try:
        custom_obj_api.delete_namespaced_custom_object(
            group=GATEWAY_API_GROUP,
            version=GATEWAY_API_VERSION,
            namespace=namespace,
            plural="httproutes",
            name=HTTP_ROUTE_NAME,
        )
    except client.exceptions.ApiException as e:
        if e.status != 404:
            raise
        log_debug("No HTTPRoute to delete")
