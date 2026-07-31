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

"""Tests for `stack manage --dir <d> explain`, which dumps the Kubernetes objects a
deployment would create.

test_k8s_objects.py covers the object content by driving ClusterInfo directly.  These
tests cover the path from a stack on disk through `init` and `deploy` to the dumped
objects, so that a break anywhere in that chain -- spec generation, the deployment
directory layout, the deployer wiring -- is caught without needing a cluster.
"""

import yaml

from conftest import make_stack_from_compose, run_stack


CLUSTER_ID = "stack-fixedclusterid0"

POD_WITH_EVERYTHING = """\
    services:
      web:
        image: nginx:local
        ports:
          - "80"  # @stack http-proxy /
        volumes:
          - web-data:/data
        environment:
          FOO: bar
    volumes:
      web-data:
    """


def parse_explain_output(stdout):
    """Split explain output into {section title: [parsed object, ...]}.

    Each object is dumped as its own YAML document without a separator, so objects are
    split on the un-indented start of a new mapping.
    """
    sections = {}
    title = None
    chunks = []
    current = []

    def flush():
        if current:
            chunks.append("\n".join(current))
        return []

    for line in stdout.splitlines():
        if line.startswith("--- ") and line.endswith(" ---"):
            current = flush()
            if title is not None:
                sections[title] = [yaml.safe_load(c) for c in chunks if c.strip()]
            title = line[4:-4]
            chunks = []
            continue
        if title is None:
            continue
        # A new object begins at a top-level key following a blank line.
        if current and not current[-1].strip() and line and not line.startswith((" ", "-")):
            current = flush()
        current.append(line)

    flush()
    if title is not None:
        sections[title] = [yaml.safe_load(c) for c in chunks if c.strip()]
    return sections


def build_deployment(tmp_path, isolated_env, deploy_to="k8s", extra_init_args=()):
    """init + deploy a fixture stack, and return the deployment directory."""
    stack_dir = make_stack_from_compose(tmp_path, POD_WITH_EVERYTHING)
    spec_file = tmp_path / "spec.yml"
    deployment_dir = tmp_path / "deployment"

    init_args = [
        "init",
        "--stack",
        str(stack_dir),
        "--deploy-to",
        deploy_to,
        "--http-proxy-fqdn",
        "test.example.com",
        "--output",
        str(spec_file),
    ]
    if deploy_to == "k8s":
        kube_config = tmp_path / "kubeconfig.yml"
        # Never loaded: `explain` builds objects without connecting to a cluster.
        kube_config.write_text("apiVersion: v1\n")
        init_args += ["--kube-config", str(kube_config)]
    init_args += list(extra_init_args)
    if deploy_to == "k8s" and "--image-registry" not in init_args:
        # The fixture image is locally built and unpublished, so a k8s deployment
        # needs a staging registry to be resolvable at all.
        init_args += ["--image-registry", "registry.example.com/org"]

    result = run_stack(init_args, isolated_env, cwd=tmp_path)
    assert result.returncode == 0, f"init failed:\n{result.stdout}\n{result.stderr}"

    result = run_stack(
        [
            "deploy",
            "--cluster",
            CLUSTER_ID,
            "--spec-file",
            str(spec_file),
            "--deployment-dir",
            str(deployment_dir),
        ],
        isolated_env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, f"deploy failed:\n{result.stdout}\n{result.stderr}"
    return deployment_dir


def explain(deployment_dir, isolated_env, cwd):
    result = run_stack(["manage", "--dir", str(deployment_dir), "explain"], isolated_env, cwd=cwd)
    assert result.returncode == 0, f"explain failed:\n{result.stdout}\n{result.stderr}"
    # Only stdout: output_main also echoes to the log file on stderr when stdout is a
    # pipe, so a combined capture would contain every object twice.
    return parse_explain_output(result.stdout)


def test_explain_emits_expected_sections(tmp_path, isolated_env):
    deployment_dir = build_deployment(tmp_path, isolated_env)

    sections = explain(deployment_dir, isolated_env, tmp_path)
    assert set(sections) == {
        "PersistentVolumeClaims",
        "Deployments",
        "Services",
        "Ingress",
        "HTTPRoute",
    }
    # No bind-mounted volumes in this spec, so no PersistentVolumes section at all.
    assert "PersistentVolumes" not in sections
    assert "ConfigMaps" not in sections


def test_explain_deployment_reflects_the_stack(tmp_path, isolated_env):
    deployment_dir = build_deployment(tmp_path, isolated_env)

    sections = explain(deployment_dir, isolated_env, tmp_path)
    assert len(sections["Deployments"]) == 1
    deployment = sections["Deployments"][0]

    assert deployment["kind"] == "Deployment"
    assert deployment["metadata"]["name"] == "deploy-web"
    # The cluster id passed to `deploy` is what ties the objects together.
    assert deployment["spec"]["selector"]["matchLabels"]["app"] == CLUSTER_ID

    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["name"] == "web"
    assert container["ports"] == [{"containerPort": 80}]
    assert {"name": "FOO", "value": "bar"} in container["env"]
    assert container["volumeMounts"] == [{"mountPath": "/data", "name": "web-data", "readOnly": False}]
    # k8s deployments pull rather than relying on a locally present image.
    assert container["imagePullPolicy"] == "Always"


def test_explain_service_and_pvc(tmp_path, isolated_env):
    deployment_dir = build_deployment(tmp_path, isolated_env)

    sections = explain(deployment_dir, isolated_env, tmp_path)

    service = sections["Services"][0]
    assert service["metadata"]["name"] == "web"
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["ports"] == [{"name": "web-80", "port": 80, "targetPort": 80}]

    pvc = sections["PersistentVolumeClaims"][0]
    assert pvc["metadata"]["name"] == "web-data"
    assert pvc["spec"]["accessModes"] == ["ReadWriteOnce"]


def test_explain_http_route_from_port_annotation(tmp_path, isolated_env):
    deployment_dir = build_deployment(tmp_path, isolated_env)

    sections = explain(deployment_dir, isolated_env, tmp_path)
    http_route = sections["HTTPRoute"][0]

    # The Gateway API rendering of the same http-proxy config as the Ingress
    # below: routing attaches to the shared stack-gateway, and TLS does not
    # appear here at all (it lives on the Gateway's listeners).
    assert http_route["spec"]["parentRefs"] == [
        {"kind": "Gateway", "name": "stack-gateway", "namespace": "kube-system"}
    ]
    assert http_route["spec"]["hostnames"] == ["test.example.com"]
    rule = http_route["spec"]["rules"][0]
    assert rule["matches"] == [{"path": {"type": "PathPrefix", "value": "/"}}]
    assert rule["backendRefs"] == [{"name": "web", "port": 80}]


def test_explain_ingress_from_port_annotation(tmp_path, isolated_env):
    deployment_dir = build_deployment(tmp_path, isolated_env)

    sections = explain(deployment_dir, isolated_env, tmp_path)
    ingress = sections["Ingress"][0]

    # The `# @stack http-proxy /` annotation on the port is what produces this rule,
    # via init writing an http-proxy route into the spec.
    rule = ingress["spec"]["rules"][0]
    assert rule["host"] == "test.example.com"
    path = rule["http"]["paths"][0]
    assert path["path"] == "/()(.*)"
    assert path["backend"]["service"] == {"name": "web", "port": {"number": 80}}
    # A non-kind k8s deployment terminates TLS.
    assert ingress["spec"]["tls"] == [{"hosts": ["test.example.com"], "secretName": "tls"}]


def test_explain_kind_deployment_has_no_tls(tmp_path, isolated_env):
    deployment_dir = build_deployment(tmp_path, isolated_env, deploy_to="k8s-kind")

    sections = explain(deployment_dir, isolated_env, tmp_path)
    ingress = sections["Ingress"][0]

    # There is no cert-manager in a local kind cluster.
    assert "tls" not in ingress["spec"]
    container = sections["Deployments"][0]["spec"]["template"]["spec"]["containers"][0]
    # Images are side-loaded into kind, so pulling would fail.
    assert "imagePullPolicy" not in container


def test_explain_image_registry_retags_local_image(tmp_path, isolated_env):
    deployment_dir = build_deployment(
        tmp_path,
        isolated_env,
        extra_init_args=["--image-registry", "registry.example.com/org"],
    )

    sections = explain(deployment_dir, isolated_env, tmp_path)
    container = sections["Deployments"][0]["spec"]["template"]["spec"]["containers"][0]
    # Salted with the last 8 characters of the cluster id.
    assert container["image"] == f"registry.example.com/org/nginx:deploy-{CLUSTER_ID[-8:]}"


def test_explain_rejects_compose_deployment(tmp_path, isolated_env):
    deployment_dir = build_deployment(tmp_path, isolated_env, deploy_to="compose")

    result = run_stack(["manage", "--dir", str(deployment_dir), "explain"], isolated_env, cwd=tmp_path)
    assert result.returncode != 0
    assert "only supported for k8s" in (result.stdout + result.stderr)
