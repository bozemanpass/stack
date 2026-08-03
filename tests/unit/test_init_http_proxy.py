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

import yaml

from conftest import run_stack

FQDN = "website-stage.example.com"

FQDN_UNUSED_WARNING = "--http-proxy-fqdn was specified but there are no HTTP proxy targets"
NO_PROXY_NOTE = "No HTTP proxy settings specified"
CLUSTERISSUER_IGNORED_NOTE = "--http-proxy-clusterissuer is only used when deploying to Kubernetes"


def init_k8s(stack_dir, output_file, env, extra_args=None):
    args = [
        "init",
        "--stack",
        str(stack_dir),
        "--deploy-to",
        "k8s",
        "--kube-config",
        "placeholder",
        "--output",
        str(output_file),
    ]
    return run_stack(args + (extra_args or []), env)


def init_compose(stack_dir, output_file, env, extra_args=None):
    args = [
        "init",
        "--stack",
        str(stack_dir),
        "--deploy-to",
        "compose",
        "--output",
        str(output_file),
    ]
    return run_stack(args + (extra_args or []), env)


def test_fqdn_without_targets_warns(minimal_stack, tmp_path, isolated_env):
    result = init_k8s(minimal_stack, tmp_path / "spec.yml", isolated_env, ["--http-proxy-fqdn", FQDN])
    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert FQDN_UNUSED_WARNING in output
    assert NO_PROXY_NOTE not in output


def test_no_proxy_settings_notes(minimal_stack, tmp_path, isolated_env):
    result = init_k8s(minimal_stack, tmp_path / "spec.yml", isolated_env)
    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert NO_PROXY_NOTE in output
    assert FQDN_UNUSED_WARNING not in output


def test_fqdn_with_explicit_target(minimal_stack, tmp_path, isolated_env):
    spec_file = tmp_path / "spec.yml"
    result = init_k8s(
        minimal_stack,
        spec_file,
        isolated_env,
        ["--http-proxy-fqdn", FQDN, "--http-proxy-target", "web:80"],
    )
    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert FQDN_UNUSED_WARNING not in output
    assert NO_PROXY_NOTE not in output

    spec = yaml.safe_load(spec_file.read_text())
    proxies = spec["network"]["http-proxy"]
    assert proxies == [
        {
            "host-name": FQDN,
            "routes": [{"path": "/", "proxy-to": "web:80"}],
            "cluster-issuer": "letsencrypt-prod",
        }
    ]


def test_fqdn_with_annotated_port(annotated_stack, tmp_path, isolated_env):
    spec_file = tmp_path / "spec.yml"
    result = init_k8s(annotated_stack, spec_file, isolated_env, ["--http-proxy-fqdn", FQDN])
    assert result.returncode == 0, result.stderr
    output = result.stdout + result.stderr
    assert FQDN_UNUSED_WARNING not in output
    assert NO_PROXY_NOTE not in output

    spec = yaml.safe_load(spec_file.read_text())
    proxies = spec["network"]["http-proxy"]
    assert proxies[0]["host-name"] == FQDN
    assert proxies[0]["routes"] == [{"path": "/", "proxy-to": "web:80"}]


# ---------------------------------------------------------------------------
# cluster issuer
#
# --http-proxy-clusterissuer carries a default, so the note about it being
# unused must key off whether the user asked for one, not off its value.
# ---------------------------------------------------------------------------


def test_compose_is_silent_about_an_unrequested_cluster_issuer(annotated_stack, tmp_path, isolated_env):
    spec_file = tmp_path / "spec.yml"
    result = init_compose(annotated_stack, spec_file, isolated_env, ["--http-proxy-fqdn", FQDN])
    assert result.returncode == 0, result.stderr
    assert CLUSTERISSUER_IGNORED_NOTE not in result.stdout + result.stderr

    # The default must not leak into a spec that cannot use it.
    spec = yaml.safe_load(spec_file.read_text())
    assert "cluster-issuer" not in spec["network"]["http-proxy"][0]


def test_compose_reports_an_explicitly_requested_cluster_issuer_is_ignored(annotated_stack, tmp_path, isolated_env):
    spec_file = tmp_path / "spec.yml"
    result = init_compose(
        annotated_stack,
        spec_file,
        isolated_env,
        ["--http-proxy-fqdn", FQDN, "--http-proxy-clusterissuer", "letsencrypt-staging"],
    )
    assert result.returncode == 0, result.stderr
    assert CLUSTERISSUER_IGNORED_NOTE in result.stdout + result.stderr

    spec = yaml.safe_load(spec_file.read_text())
    assert "cluster-issuer" not in spec["network"]["http-proxy"][0]


def test_k8s_keeps_the_default_cluster_issuer_without_comment(annotated_stack, tmp_path, isolated_env):
    spec_file = tmp_path / "spec.yml"
    result = init_k8s(annotated_stack, spec_file, isolated_env, ["--http-proxy-fqdn", FQDN])
    assert result.returncode == 0, result.stderr
    assert CLUSTERISSUER_IGNORED_NOTE not in result.stdout + result.stderr

    spec = yaml.safe_load(spec_file.read_text())
    assert spec["network"]["http-proxy"][0]["cluster-issuer"] == "letsencrypt-prod"


def test_k8s_honours_an_explicit_cluster_issuer(annotated_stack, tmp_path, isolated_env):
    spec_file = tmp_path / "spec.yml"
    result = init_k8s(
        annotated_stack,
        spec_file,
        isolated_env,
        ["--http-proxy-fqdn", FQDN, "--http-proxy-clusterissuer", "letsencrypt-staging"],
    )
    assert result.returncode == 0, result.stderr
    assert CLUSTERISSUER_IGNORED_NOTE not in result.stdout + result.stderr

    spec = yaml.safe_load(spec_file.read_text())
    assert spec["network"]["http-proxy"][0]["cluster-issuer"] == "letsencrypt-staging"
