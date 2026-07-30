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

"""Tests for the Kubernetes objects generated from a pod file plus a deployment spec.

These drive ClusterInfo directly and assert on the serialized form of what it builds --
the same transformation the API client applies on the way to the cluster.  Previously
this content was only exercised by deploying a whole stack and seeing whether it ran,
which gave no indication of *which* piece of generated state was wrong.

No cluster is involved: ClusterInfo parses files and builds objects, and K8sDeployer
reaches a cluster only via connect_api(), which is never called here.
"""

import pytest

from conftest import TEST_CLUSTER_ID, k8s_dict, make_cluster_info


MINIMAL_POD = """\
    services:
      web:
        image: nginx:local
        ports:
          - "80"
    """


def k8s_spec(**overrides):
    """A k8s deployment spec for the single-service pod above."""
    spec = {
        "stack": "teststack",
        "deploy-to": "k8s",
    }
    spec.update(overrides)
    return spec


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


def test_service_is_clusterip_with_matching_selector(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec())

    services = cluster_info.get_services()
    assert len(services) == 1
    svc = k8s_dict(services[0])

    assert svc["metadata"]["name"] == "web"
    assert svc["metadata"]["labels"] == {"app": TEST_CLUSTER_ID, "service": "web"}
    assert svc["spec"]["type"] == "ClusterIP"
    # The selector must match the labels put on the pod template, or the Service
    # resolves to no endpoints and the deployment appears to hang.
    assert svc["spec"]["selector"] == {"app": TEST_CLUSTER_ID, "service": "web"}
    assert svc["spec"]["ports"] == [{"name": "web-80", "port": 80, "targetPort": 80}]


def test_service_port_forms_reduce_to_the_container_port(tmp_path):
    pod = """\
        services:
          web:
            image: nginx:local
            ports:
              - "80"
              - "8080:81"
              - "127.0.0.1:8443:82"
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec())

    svc = k8s_dict(cluster_info.get_services()[0])
    assert [p["port"] for p in svc["spec"]["ports"]] == [80, 81, 82]
    assert [p["targetPort"] for p in svc["spec"]["ports"]] == [80, 81, 82]


def test_service_strips_udp_suffix_from_port(tmp_path):
    pod = """\
        services:
          dns:
            image: coredns:local
            ports:
              - "53/udp"
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec())

    svc = k8s_dict(cluster_info.get_services()[0])
    assert svc["spec"]["ports"] == [{"name": "dns-53", "port": 53, "targetPort": 53}]


def test_service_omitted_when_no_ports(tmp_path):
    pod = """\
        services:
          worker:
            image: worker:local
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec())

    assert cluster_info.get_services() == []


# ---------------------------------------------------------------------------
# Ingress
# ---------------------------------------------------------------------------


def proxy_spec(routes, host="test.example.com", **overrides):
    return k8s_spec(network={"http-proxy": [{"host-name": host, "routes": routes}]}, **overrides)


def test_no_ingress_without_http_proxy(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec())
    assert cluster_info.get_ingress() is None


def test_ingress_root_path_becomes_capture_groups(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, proxy_spec([{"path": "/", "proxy-to": "web:80"}]))

    ingress = k8s_dict(cluster_info.get_ingress())
    path = ingress["spec"]["rules"][0]["http"]["paths"][0]
    # The rewrite-target annotation below is "/$2", so every path must expose the
    # remainder of the URL as its second capture group.
    assert path["path"] == "/()(.*)"
    assert path["pathType"] == "ImplementationSpecific"
    assert path["backend"]["service"] == {"name": "web", "port": {"number": 80}}
    assert ingress["metadata"]["annotations"]["nginx.ingress.kubernetes.io/rewrite-target"] == "/$2"
    assert ingress["metadata"]["annotations"]["nginx.ingress.kubernetes.io/use-regex"] == "true"
    assert ingress["spec"]["ingressClassName"] == "nginx"
    assert ingress["spec"]["rules"][0]["host"] == "test.example.com"


def test_ingress_empty_path_treated_as_root(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, proxy_spec([{"path": "", "proxy-to": "web:80"}]))

    ingress = k8s_dict(cluster_info.get_ingress())
    assert ingress["spec"]["rules"][0]["http"]["paths"][0]["path"] == "/()(.*)"


def test_ingress_missing_path_defaults_to_root(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, proxy_spec([{"proxy-to": "web:80"}]))

    ingress = k8s_dict(cluster_info.get_ingress())
    assert ingress["spec"]["rules"][0]["http"]["paths"][0]["path"] == "/()(.*)"


def test_ingress_subpath_gets_optional_slash_and_remainder(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, proxy_spec([{"path": "/api", "proxy-to": "web:80"}]))

    ingress = k8s_dict(cluster_info.get_ingress())
    assert ingress["spec"]["rules"][0]["http"]["paths"][0]["path"] == "/api(/?)(.*)"


def test_ingress_subpath_normalizes_surrounding_slashes(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, proxy_spec([{"path": "api/v1/", "proxy-to": "web:80"}]))

    ingress = k8s_dict(cluster_info.get_ingress())
    assert ingress["spec"]["rules"][0]["http"]["paths"][0]["path"] == "/api/v1(/?)(.*)"


def test_ingress_path_with_explicit_capture_group_passed_through(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, proxy_spec([{"path": "/custom(.*)", "proxy-to": "web:80"}]))

    ingress = k8s_dict(cluster_info.get_ingress())
    # A path that already supplies its own regex is left alone.
    assert ingress["spec"]["rules"][0]["http"]["paths"][0]["path"] == "/custom(.*)"


def test_ingress_multiple_routes_preserve_order(tmp_path):
    routes = [
        {"path": "/api", "proxy-to": "web:80"},
        {"path": "/admin", "proxy-to": "admin:81"},
    ]
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, proxy_spec(routes))

    ingress = k8s_dict(cluster_info.get_ingress())
    paths = ingress["spec"]["rules"][0]["http"]["paths"]
    assert [p["path"] for p in paths] == ["/api(/?)(.*)", "/admin(/?)(.*)"]
    assert [p["backend"]["service"]["name"] for p in paths] == ["web", "admin"]
    assert [p["backend"]["service"]["port"]["number"] for p in paths] == [80, 81]


def test_ingress_without_tls_has_no_tls_section(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, proxy_spec([{"path": "/", "proxy-to": "web:80"}]))

    ingress = k8s_dict(cluster_info.get_ingress(use_tls=False))
    assert "tls" not in ingress["spec"]


def test_ingress_tls_defaults_to_proxy_host(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, proxy_spec([{"path": "/", "proxy-to": "web:80"}]))

    ingress = k8s_dict(cluster_info.get_ingress(use_tls=True))
    assert ingress["spec"]["tls"] == [{"hosts": ["test.example.com"], "secretName": "tls"}]
    # With no supplied certificate, cert-manager is asked to issue one.
    assert ingress["metadata"]["annotations"]["cert-manager.io/cluster-issuer"] == "letsencrypt-prod"


def test_ingress_tls_uses_supplied_certificate(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, proxy_spec([{"path": "/", "proxy-to": "web:80"}]))
    certificate = {"spec": {"dnsNames": ["a.example.com", "b.example.com"], "secretName": "existing-tls"}}

    ingress = k8s_dict(cluster_info.get_ingress(use_tls=True, certificate=certificate))
    assert ingress["spec"]["tls"] == [
        {"hosts": ["a.example.com", "b.example.com"], "secretName": "existing-tls"}
    ]
    # An existing certificate means cert-manager must not be asked to issue another.
    assert "cert-manager.io/cluster-issuer" not in ingress["metadata"]["annotations"]


def test_ingress_cluster_issuer_from_spec_overrides_default(tmp_path):
    spec = k8s_spec(
        network={
            "http-proxy": [
                {
                    "host-name": "test.example.com",
                    "cluster-issuer": "letsencrypt-staging",
                    "routes": [{"path": "/", "proxy-to": "web:80"}],
                }
            ]
        }
    )
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, spec)

    ingress = k8s_dict(cluster_info.get_ingress(use_tls=True))
    assert ingress["metadata"]["annotations"]["cert-manager.io/cluster-issuer"] == "letsencrypt-staging"


# ---------------------------------------------------------------------------
# Resource requirements
# ---------------------------------------------------------------------------


def test_container_resources_default_when_spec_is_silent(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec())

    container = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]
    assert container["resources"] == {
        "requests": {"cpu": "0.1", "memory": "200M"},
        "limits": {"cpu": "1.0", "memory": "2000M"},
    }


def test_container_resources_converted_from_human_sizes(tmp_path):
    spec = k8s_spec(
        resources={
            "containers": {
                "web": {
                    "reservations": {"cpus": "0.5", "memory": "512M"},
                    "limits": {"cpus": "2", "memory": "4G"},
                }
            }
        }
    )
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, spec)

    container = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]
    # Sizes are parsed by humanfriendly then re-emitted in megabytes.
    assert container["resources"] == {
        "requests": {"cpu": "0.5", "memory": "512M"},
        "limits": {"cpu": "2.0", "memory": "4000M"},
    }


def test_container_reservations_only_yields_no_limits(tmp_path):
    spec = k8s_spec(resources={"containers": {"web": {"reservations": {"memory": "256M"}}}})
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, spec)

    container = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]
    assert container["resources"] == {"requests": {"memory": "256M"}}


# ---------------------------------------------------------------------------
# PersistentVolumeClaims and PersistentVolumes
# ---------------------------------------------------------------------------


VOLUME_POD = """\
    services:
      web:
        image: nginx:local
        volumes:
          - web-data:/data
    volumes:
      web-data:
    """


def test_pvc_for_auto_assigned_volume(tmp_path):
    cluster_info = make_cluster_info(tmp_path, VOLUME_POD, k8s_spec(volumes={"web-data": None}))

    pvcs = cluster_info.get_pvcs()
    assert len(pvcs) == 1
    pvc = k8s_dict(pvcs[0])

    assert pvc["metadata"]["name"] == "web-data"
    assert pvc["metadata"]["labels"] == {
        "app": TEST_CLUSTER_ID,
        "volume-label": f"{TEST_CLUSTER_ID}-web-data",
    }
    assert pvc["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert pvc["spec"]["resources"] == {"requests": {"storage": "2000M"}}
    # No storage class and no volume name: the cluster picks and binds a volume.
    assert "storageClassName" not in pvc["spec"]
    assert "volumeName" not in pvc["spec"]


def test_pvc_for_bind_mounted_volume_is_manually_bound(tmp_path):
    cluster_info = make_cluster_info(tmp_path, VOLUME_POD, k8s_spec(volumes={"web-data": "/srv/data"}))

    pvc = k8s_dict(cluster_info.get_pvcs()[0])
    assert pvc["spec"]["storageClassName"] == "manual"
    # Must name the PV built below, or the claim binds to the wrong volume.
    assert pvc["spec"]["volumeName"] == f"{TEST_CLUSTER_ID}-web-data"


def test_pvc_storage_size_from_spec(tmp_path):
    spec = k8s_spec(
        volumes={"web-data": None},
        resources={"volumes": {"web-data": {"reservations": {"storage": "10G"}}}},
    )
    cluster_info = make_cluster_info(tmp_path, VOLUME_POD, spec)

    pvc = k8s_dict(cluster_info.get_pvcs()[0])
    assert pvc["spec"]["resources"] == {"requests": {"storage": "10000M"}}


def test_volume_in_spec_but_not_in_pod_file_is_ignored(tmp_path):
    spec = k8s_spec(volumes={"web-data": None, "stale-data": None})
    cluster_info = make_cluster_info(tmp_path, VOLUME_POD, spec)

    assert [k8s_dict(p)["metadata"]["name"] for p in cluster_info.get_pvcs()] == ["web-data"]


def test_no_pv_for_auto_assigned_volume(tmp_path):
    cluster_info = make_cluster_info(tmp_path, VOLUME_POD, k8s_spec(volumes={"web-data": None}))

    # Without a host path there is nothing to bind, so the node allocates instead.
    assert cluster_info.get_pvs() == []


def test_pv_for_bind_mounted_volume(tmp_path):
    cluster_info = make_cluster_info(tmp_path, VOLUME_POD, k8s_spec(volumes={"web-data": "/srv/data"}))

    pvs = cluster_info.get_pvs()
    assert len(pvs) == 1
    pv = k8s_dict(pvs[0])

    assert pv["metadata"]["name"] == f"{TEST_CLUSTER_ID}-web-data"
    assert pv["metadata"]["labels"] == {"volume-label": f"{TEST_CLUSTER_ID}-web-data"}
    assert pv["spec"]["storageClassName"] == "manual"
    assert pv["spec"]["accessModes"] == ["ReadWriteOnce"]
    assert pv["spec"]["hostPath"] == {"path": "/srv/data"}
    assert pv["spec"]["capacity"] == {"storage": "2000M"}


def test_pv_host_path_rewritten_for_kind(tmp_path):
    spec = k8s_spec(volumes={"web-data": "/srv/data"})
    spec["deploy-to"] = "k8s-kind"
    cluster_info = make_cluster_info(tmp_path, VOLUME_POD, spec)

    pv = k8s_dict(cluster_info.get_pvs()[0])
    # In kind the host path is a mount inside the node container, not the real host path.
    assert pv["spec"]["hostPath"] == {"path": "/mnt/web-data"}


def test_no_pv_for_relative_host_path(tmp_path):
    cluster_info = make_cluster_info(tmp_path, VOLUME_POD, k8s_spec(volumes={"web-data": "./data/web-data"}))

    # A relative path cannot be bound; the generator warns and skips it rather than
    # emitting a PV the cluster would reject.
    assert cluster_info.get_pvs() == []


# ---------------------------------------------------------------------------
# ConfigMaps
# ---------------------------------------------------------------------------


def test_configmap_content_read_from_directory(tmp_path):
    config_dir = tmp_path / "configmaps" / "web-config"
    config_dir.mkdir(parents=True)
    (config_dir / "app.conf").write_text("key = value\n")
    (config_dir / "extra.conf").write_text("other = thing\n")
    # A nested directory is not part of a single-level configmap.
    (config_dir / "nested").mkdir()
    (config_dir / "nested" / "ignored.conf").write_text("ignored\n")

    pod = """\
        services:
          web:
            image: nginx:local
            volumes:
              - web-config:/etc/nginx/conf.d:ro
        volumes:
          web-config:
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec(configmaps={"web-config": "./configmaps/web-config"}))

    cfgmaps = cluster_info.get_configmaps()
    assert len(cfgmaps) == 1
    cfgmap = k8s_dict(cfgmaps[0])

    assert cfgmap["metadata"]["name"] == "web-config"
    assert cfgmap["metadata"]["labels"] == {"configmap-label": "web-config"}
    assert sorted(cfgmap["binaryData"].keys()) == ["app.conf", "extra.conf"]
    import base64

    assert base64.b64decode(cfgmap["binaryData"]["app.conf"]).decode() == "key = value\n"


def test_configmap_backed_volume_is_not_a_pvc_volume(tmp_path):
    config_dir = tmp_path / "configmaps" / "web-config"
    config_dir.mkdir(parents=True)
    (config_dir / "app.conf").write_text("key = value\n")

    pod = """\
        services:
          web:
            image: nginx:local
            volumes:
              - web-config:/etc/nginx/conf.d:ro
              - web-data:/data
        volumes:
          web-config:
          web-data:
        """
    spec = k8s_spec(configmaps={"web-config": "./configmaps/web-config"}, volumes={"web-data": None})
    cluster_info = make_cluster_info(tmp_path, pod, spec)

    volumes = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["volumes"]
    by_name = {v["name"]: v for v in volumes}
    assert by_name["web-config"] == {"name": "web-config", "configMap": {"name": "web-config"}}
    assert by_name["web-data"] == {
        "name": "web-data",
        "persistentVolumeClaim": {"claimName": "web-data"},
    }


# ---------------------------------------------------------------------------
# Deployments: volume mounts
# ---------------------------------------------------------------------------


def test_volume_mount_read_only_flag(tmp_path):
    pod = """\
        services:
          web:
            image: nginx:local
            volumes:
              - rw-data:/rw
              - ro-data:/ro:ro
              - explicit-rw:/erw:rw
        volumes:
          rw-data:
          ro-data:
          explicit-rw:
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec())

    mounts = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]
    assert mounts == [
        {"mountPath": "/rw", "name": "rw-data", "readOnly": False},
        {"mountPath": "/ro", "name": "ro-data", "readOnly": True},
        {"mountPath": "/erw", "name": "explicit-rw", "readOnly": False},
    ]


# ---------------------------------------------------------------------------
# Deployments: environment
# ---------------------------------------------------------------------------


def test_environment_from_compose_mapping(tmp_path):
    pod = """\
        services:
          web:
            image: nginx:local
            environment:
              PLAIN: value
              NUMERIC: 42
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec())

    envs = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]["env"]
    by_name = {e["name"]: e["value"] for e in envs}
    assert by_name["PLAIN"] == "value"
    assert by_name["NUMERIC"] == "42"


@pytest.mark.xfail(
    strict=True,
    reason="A YAML boolean reaches the container as 'True', not 'true'.  "
    "envs_from_environment_variables_map() has a branch that lowercases bools, but "
    "envs_from_compose_file() has already run str() over the value by then, so the "
    "branch never fires.  Compose emits 'true' for the same stack.",
)
def test_boolean_environment_value_is_lowercased(tmp_path):
    pod = """\
        services:
          web:
            image: nginx:local
            environment:
              TRUTHY: true
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec())

    envs = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]["env"]
    by_name = {e["name"]: e["value"] for e in envs}
    assert by_name["TRUTHY"] == "true"


def test_environment_from_compose_sequence(tmp_path):
    pod = """\
        services:
          web:
            image: nginx:local
            environment:
              - PLAIN=value
              - EMPTY=
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec())

    envs = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]["env"]
    by_name = {e["name"]: e.get("value") for e in envs}
    assert by_name["PLAIN"] == "value"
    assert by_name["EMPTY"] in (None, "")


def test_environment_from_env_file_relative_to_pod_dir(tmp_path):
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "web.env").write_text("FROM_FILE=file-value\nSHARED=file-wins-unless-overridden\n")

    pod = """\
        services:
          web:
            image: nginx:local
            env_file:
              - env/web.env
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec())

    envs = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]["env"]
    by_name = {e["name"]: e.get("value") for e in envs}
    assert by_name["FROM_FILE"] == "file-value"


@pytest.mark.xfail(
    strict=True,
    reason="env_file wins over an inline environment value, which is the opposite of "
    "compose precedence, so the same stack gets different values under k8s and "
    "compose.  get_deployments() calls merge_envs(new, existing) and merge_envs "
    "lets its second argument win, so already-merged values beat later ones.",
)
def test_inline_environment_overrides_env_file(tmp_path):
    (tmp_path / "env").mkdir()
    (tmp_path / "env" / "web.env").write_text("SHARED=from-file\n")

    pod = """\
        services:
          web:
            image: nginx:local
            env_file:
              - env/web.env
            environment:
              SHARED: from-inline
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec())

    envs = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]["env"]
    by_name = {e["name"]: e.get("value") for e in envs}
    assert by_name["SHARED"] == "from-inline"


# ---------------------------------------------------------------------------
# Deployments: liveness probe from healthcheck
# ---------------------------------------------------------------------------


def test_no_liveness_probe_without_healthcheck(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec())

    container = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]
    assert "livenessProbe" not in container


def test_liveness_probe_cmd_shell_wrapped_in_shell(tmp_path):
    pod = """\
        services:
          web:
            image: nginx:local
            healthcheck:
              test: ["CMD-SHELL", "curl -f http://localhost || exit 1"]
              interval: 15s
              timeout: 5s
              retries: 4
              start_period: 30s
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec())

    container = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]
    assert container["livenessProbe"] == {
        "exec": {"command": ["/bin/sh", "-c", "curl -f http://localhost || exit 1"]},
        "initialDelaySeconds": 30,
        "periodSeconds": 15,
        "timeoutSeconds": 5,
        "failureThreshold": 4,
    }


def test_liveness_probe_cmd_strips_only_the_type(tmp_path):
    pod = """\
        services:
          web:
            image: nginx:local
            healthcheck:
              test: ["CMD", "wget", "-q", "-O", "-", "http://localhost"]
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec())

    probe = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]["livenessProbe"]
    assert probe["exec"]["command"] == ["wget", "-q", "-O", "-", "http://localhost"]
    # Compose defaults, translated to the k8s probe fields.
    assert probe["initialDelaySeconds"] == 0
    assert probe["periodSeconds"] == 30
    assert probe["timeoutSeconds"] == 30
    assert probe["failureThreshold"] == 3


def test_liveness_probe_time_units_converted(tmp_path):
    pod = """\
        services:
          web:
            image: nginx:local
            healthcheck:
              test: ["CMD", "true"]
              interval: 2m
              timeout: 90s
              start_period: 1h
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec())

    probe = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]["livenessProbe"]
    assert probe["periodSeconds"] == 120
    assert probe["timeoutSeconds"] == 90
    assert probe["initialDelaySeconds"] == 3600


# ---------------------------------------------------------------------------
# Deployments: image tagging
# ---------------------------------------------------------------------------


def test_image_left_alone_without_registry(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec())

    container = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "nginx:local"


def test_local_image_retagged_for_registry_with_deployment_salt(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec(**{"image-registry": "registry.example.com/org"}))

    container = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]
    # The tag is salted with the last 8 characters of the deployment id so that
    # concurrent deployments of the same stack do not share a remote tag.
    assert container["image"] == "registry.example.com/org/nginx:deploy-89abcdef"


def test_released_two_part_image_not_retagged_for_registry(tmp_path):
    pod = """\
        services:
          web:
            image: nginx:1.27
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec(**{"image-registry": "registry.example.com/org"}))

    container = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]
    # Only :local and :stack images are built here; anything else is pulled as named.
    assert container["image"] == "nginx:1.27"


@pytest.mark.parametrize(
    "image, expected",
    [
        # Released images are pulled as named, however they are qualified.
        ("ghcr.io/example/nginx:1.27", "ghcr.io/example/nginx:1.27"),
        # A stack-built image is redirected at the deployment's registry either way.
        ("ghcr.io/example/nginx:stack", "registry.example.com/org/nginx:deploy-89abcdef"),
    ],
)
def test_registry_qualified_image_handled(tmp_path, image, expected):
    pod = f"""\
        services:
          web:
            image: {image}
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec(**{"image-registry": "registry.example.com/org"}))

    container = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == expected


def test_image_pull_policy_passed_through(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec())

    deployment = k8s_dict(cluster_info.get_deployments(image_pull_policy="Always")[0])
    assert deployment["spec"]["template"]["spec"]["containers"][0]["imagePullPolicy"] == "Always"


# ---------------------------------------------------------------------------
# Deployments: pod-level structure
# ---------------------------------------------------------------------------


def test_deployment_shape_and_defaults(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec())

    deployment = k8s_dict(cluster_info.get_deployments()[0])
    assert deployment["apiVersion"] == "apps/v1"
    assert deployment["kind"] == "Deployment"
    assert deployment["metadata"]["name"] == "deploy-web"
    assert deployment["spec"]["replicas"] == 1
    assert deployment["spec"]["selector"] == {"matchLabels": {"app": TEST_CLUSTER_ID}}
    assert deployment["spec"]["template"]["metadata"]["labels"] == {
        "app": TEST_CLUSTER_ID,
        "service": "web",
    }
    assert deployment["spec"]["template"]["spec"]["imagePullSecrets"] == [{"name": "stack-image-registry"}]
    assert deployment["spec"]["template"]["spec"]["containers"][0]["ports"] == [{"containerPort": 80}]


def test_replicas_from_spec(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec(replicas=3))

    assert k8s_dict(cluster_info.get_deployments()[0])["spec"]["replicas"] == 3


def test_localhost_host_aliases_for_service_name(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec())

    pod_spec = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]
    # Every service can reach itself by its own name, as it could under compose.
    assert pod_spec["hostAliases"] == [{"hostnames": ["web", "web.local"], "ip": "127.0.0.1"}]


def test_one_deployment_per_service(tmp_path):
    pod = """\
        services:
          web:
            image: nginx:local
          worker:
            image: worker:local
        """
    cluster_info = make_cluster_info(tmp_path, pod, k8s_spec())

    deployments = cluster_info.get_deployments()
    assert [k8s_dict(d)["metadata"]["name"] for d in deployments] == ["deploy-web", "deploy-worker"]


# ---------------------------------------------------------------------------
# Deployments: security context
# ---------------------------------------------------------------------------


def test_security_context_defaults_to_unprivileged(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec())

    container = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]
    assert container["securityContext"] == {"privileged": False}


def test_privileged_from_spec(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec(security={"web": {"privileged": "true"}}))

    container = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]
    assert container["securityContext"]["privileged"] is True


def test_capabilities_from_spec(tmp_path):
    spec = k8s_spec(security={"web": {"capabilities": ["NET_ADMIN", "SYS_TIME"]}})
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, spec)

    container = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]["containers"][0]
    assert container["securityContext"]["capabilities"] == {"add": ["NET_ADMIN", "SYS_TIME"]}


# ---------------------------------------------------------------------------
# Deployments: annotations, labels, affinity, tolerations
# ---------------------------------------------------------------------------


def test_annotations_substitute_container_name(tmp_path):
    spec = k8s_spec(annotations={"example.com/{name}-role": "frontend"})
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, spec)

    metadata = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["metadata"]
    assert metadata["annotations"] == {"example.com/web-role": "frontend"}


def test_labels_substitute_container_name_and_keep_defaults(tmp_path):
    spec = k8s_spec(labels={"{name}-tier": "web"})
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, spec)

    metadata = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["metadata"]
    assert metadata["labels"] == {
        "app": TEST_CLUSTER_ID,
        "service": "web",
        "web-tier": "web",
    }


def test_node_affinity_from_spec(tmp_path):
    spec = k8s_spec(**{"node-affinities": [{"label": "disk", "value": "ssd"}]})
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, spec)

    pod_spec = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]
    terms = pod_spec["affinity"]["nodeAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"]
    assert terms == [{"matchExpressions": [{"key": "disk", "operator": "In", "values": ["ssd"]}]}]


def test_node_tolerations_from_spec(tmp_path):
    spec = k8s_spec(**{"node-tolerations": [{"key": "dedicated", "value": "stack"}]})
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, spec)

    pod_spec = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]["spec"]
    assert pod_spec["tolerations"] == [
        {"effect": "NoSchedule", "key": "dedicated", "operator": "Equal", "value": "stack"}
    ]


def test_no_affinity_or_tolerations_by_default(tmp_path):
    cluster_info = make_cluster_info(tmp_path, MINIMAL_POD, k8s_spec())

    template = k8s_dict(cluster_info.get_deployments()[0])["spec"]["template"]
    assert "affinity" not in template["spec"]
    assert "tolerations" not in template["spec"]
    assert "annotations" not in template["metadata"]
