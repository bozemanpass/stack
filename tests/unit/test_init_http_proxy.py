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
