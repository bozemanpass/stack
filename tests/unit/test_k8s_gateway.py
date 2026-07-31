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

"""Tests for the Gateway API resources used on Gateway-provisioned clusters.

HTTPRoute generation is driven through ClusterInfo like the other k8s object
tests; the listener construction and hostname coverage logic in
stack.deploy.k8s.gateway is pure and is tested directly.  No cluster is
involved.
"""

from conftest import make_cluster_info

from stack.deploy.k8s import gateway


MINIMAL_POD = """\
    services:
      web:
        image: nginx:local
        ports:
          - "80"
    """


def k8s_spec(**overrides):
    spec = {
        "stack": "teststack",
        "deploy-to": "k8s",
    }
    spec.update(overrides)
    return spec


def proxy_spec(routes, host="test.example.com", **overrides):
    return k8s_spec(network={"http-proxy": [{"host-name": host, "routes": routes}]}, **overrides)


def get_http_route(tmp_path, spec):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, spec)
    return cluster_info.get_http_route(gateway.GATEWAY_NAME, gateway.GATEWAY_NAMESPACE)


# ---------------------------------------------------------------------------
# HTTPRoute generation
# ---------------------------------------------------------------------------


def test_no_http_route_without_http_proxy(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec())
    assert cluster_info.get_http_route(gateway.GATEWAY_NAME, gateway.GATEWAY_NAMESPACE) is None


def test_http_route_attaches_to_the_shared_gateway(tmp_path):
    route = get_http_route(tmp_path, proxy_spec([{"path": "/", "proxy-to": "web:80"}]))

    assert route["apiVersion"] == "gateway.networking.k8s.io/v1"
    assert route["kind"] == "HTTPRoute"
    # The route names the Gateway; nothing in it names traefik or any other
    # implementation, which stays a property of the machine.
    assert route["spec"]["parentRefs"] == [
        {"kind": "Gateway", "name": "stack-gateway", "namespace": "kube-system"}
    ]
    assert route["spec"]["hostnames"] == ["test.example.com"]


def test_http_route_root_path_is_prefix_match_without_rewrite(tmp_path):
    route = get_http_route(tmp_path, proxy_spec([{"path": "/", "proxy-to": "web:80"}]))

    rule = route["spec"]["rules"][0]
    assert rule["matches"] == [{"path": {"type": "PathPrefix", "value": "/"}}]
    assert rule["backendRefs"] == [{"name": "web", "port": 80}]
    # Proxying "/" to the backend's "/" needs no rewrite.
    assert "filters" not in rule


def test_http_route_empty_and_missing_path_treated_as_root(tmp_path):
    for routes in ([{"path": "", "proxy-to": "web:80"}], [{"proxy-to": "web:80"}]):
        route = get_http_route(tmp_path, proxy_spec(routes))
        assert route["spec"]["rules"][0]["matches"] == [{"path": {"type": "PathPrefix", "value": "/"}}]


def test_http_route_subpath_is_stripped_via_rewrite(tmp_path):
    route = get_http_route(tmp_path, proxy_spec([{"path": "/api", "proxy-to": "web:80"}]))

    rule = route["spec"]["rules"][0]
    assert rule["matches"] == [{"path": {"type": "PathPrefix", "value": "/api"}}]
    # The backend sees paths relative to its own root, matching the
    # rewrite-target behavior of the Ingress arrangement.
    assert rule["filters"] == [
        {
            "type": "URLRewrite",
            "urlRewrite": {"path": {"type": "ReplacePrefixMatch", "replacePrefixMatch": "/"}},
        }
    ]


def test_http_route_subpath_normalizes_surrounding_slashes(tmp_path):
    route = get_http_route(tmp_path, proxy_spec([{"path": "api/v1/", "proxy-to": "web:80"}]))

    assert route["spec"]["rules"][0]["matches"] == [{"path": {"type": "PathPrefix", "value": "/api/v1"}}]


def test_http_route_regex_path_degrades_to_prefix(tmp_path):
    # The Ingress arrangement accepted nginx regex paths; the Gateway API has
    # no core regex matching, so only the literal prefix is kept.
    route = get_http_route(tmp_path, proxy_spec([{"path": "/custom(.*)", "proxy-to": "web:80"}]))

    assert route["spec"]["rules"][0]["matches"] == [{"path": {"type": "PathPrefix", "value": "/custom"}}]


def test_http_route_multiple_routes_preserve_order(tmp_path):
    routes = [
        {"path": "/api", "proxy-to": "web:80"},
        {"path": "/admin", "proxy-to": "admin:81"},
    ]
    route = get_http_route(tmp_path, proxy_spec(routes))

    rules = route["spec"]["rules"]
    assert [r["matches"][0]["path"]["value"] for r in rules] == ["/api", "/admin"]
    assert [r["backendRefs"][0]["name"] for r in rules] == ["web", "admin"]
    assert [r["backendRefs"][0]["port"] for r in rules] == [80, 81]


# ---------------------------------------------------------------------------
# Gateway listeners
# ---------------------------------------------------------------------------


def test_https_listener_shape(tmp_path):
    listener = gateway.https_listener_for_deployment("mydeployment", "app.example.com")

    assert listener == {
        "name": "mydeployment-https",
        "port": 8443,
        "protocol": "HTTPS",
        "hostname": "app.example.com",
        "allowedRoutes": {"namespaces": {"from": "All"}},
        "tls": {
            "mode": "Terminate",
            "certificateRefs": [{"name": "mydeployment-tls"}],
        },
    }


def test_hostname_matches_exact_and_wildcard():
    assert gateway.hostname_matches("app.example.com", "app.example.com")
    # A wildcard covers exactly one extra label, like a wildcard certificate.
    assert gateway.hostname_matches("*.example.com", "app.example.com")
    assert not gateway.hostname_matches("*.example.com", "example.com")
    assert not gateway.hostname_matches("*.example.com", "a.b.example.com")
    assert not gateway.hostname_matches("other.example.com", "app.example.com")
    assert not gateway.hostname_matches(None, "app.example.com")


def gateway_with_listeners(listeners):
    return {"spec": {"listeners": listeners}}


def test_listener_covering_host_ignores_http_listeners():
    gw = gateway_with_listeners(
        [{"name": "web", "protocol": "HTTP", "hostname": "app.example.com"}]
    )
    assert gateway.https_listener_covering_host(gw, "app.example.com") is None


def test_listener_covering_host_finds_wildcard():
    # The machine-provisioned wildcard listener arrangement: a deployment under
    # the covered domain needs no listener of its own.
    wildcard = {"name": "websecure", "protocol": "HTTPS", "hostname": "*.example.com"}
    gw = gateway_with_listeners([wildcard])
    assert gateway.https_listener_covering_host(gw, "app.example.com") is wildcard
    assert gateway.https_listener_covering_host(gw, "app.elsewhere.com") is None


def test_listener_covering_host_finds_exact():
    exact = gateway.https_listener_for_deployment("mydeployment", "app.example.com")
    gw = gateway_with_listeners([exact])
    assert gateway.https_listener_covering_host(gw, "app.example.com") is exact
