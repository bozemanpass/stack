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

"""The spec's `kube-config` value as a reference rather than a path.

A deployment directory is often a git repository, so the property under test
throughout is that a deployment made from a referenced credential contains no
credential: the reference travels in the spec file and is resolved only when
the deployer connects.  No cluster is involved -- resolution is driven directly,
and the deployment side goes through `init` and `deploy` in a subprocess.
"""

import textwrap

import pytest

from conftest import make_stack_from_compose, run_stack

from stack.deploy.kube_config import (
    is_deferred_reference,
    kube_config_file,
    reference_scheme,
    resolve_reference,
    validate_reference,
)


KUBE_CONFIG_CONTENT = "apiVersion: v1\nkind: Config\nclusters: []\n"

POD = """\
    services:
      web:
        image: nginx:local
        ports:
          - "80"
    """


class FakeSpec:
    """Just the one accessor kube_config_file reads."""

    def __init__(self, value):
        self.value = value

    def get_kube_config(self):
        return self.value


# --- what counts as a reference ---------------------------------------------


@pytest.mark.parametrize(
    "value, scheme",
    [
        ("/home/me/.kube/config", None),
        ("relative/kubeconfig.yml", None),
        ("~/.kube/config", None),
        ("env:KUBECONFIG_DATA", "env"),
        ("env-file:KUBECONFIG", "env-file"),
        ("file:/etc/stack/kubeconfig.yml", "file"),
        ("exec:sops -d cluster.enc.yml", "exec"),
    ],
)
def test_reference_scheme(value, scheme):
    assert reference_scheme(value) == scheme
    assert is_deferred_reference(value) == (scheme is not None)


def test_validate_accepts_paths_and_known_schemes():
    # A bare path is the original meaning of the field and stays valid.
    validate_reference("/home/me/.kube/config")
    validate_reference("env:KUBECONFIG_DATA")


def test_validate_rejects_an_unknown_scheme(capsys):
    with pytest.raises(SystemExit):
        validate_reference("vault:secret/data/cluster")
    assert "unknown scheme 'vault:'" in capsys.readouterr().err


def test_validate_rejects_an_empty_reference(capsys):
    with pytest.raises(SystemExit):
        validate_reference("env:")
    assert "names nothing after 'env:'" in capsys.readouterr().err


# --- resolution --------------------------------------------------------------


def test_env_holds_the_config_itself(monkeypatch):
    monkeypatch.setenv("KUBECONFIG_DATA", KUBE_CONFIG_CONTENT)
    assert resolve_reference("env:KUBECONFIG_DATA") == KUBE_CONFIG_CONTENT


def test_env_file_holds_a_path(monkeypatch, tmp_path):
    config = tmp_path / "kubeconfig.yml"
    config.write_text(KUBE_CONFIG_CONTENT)
    monkeypatch.setenv("KUBECONFIG", str(config))
    assert resolve_reference("env-file:KUBECONFIG") == KUBE_CONFIG_CONTENT


def test_file_reads_at_resolve_time(tmp_path):
    config = tmp_path / "kubeconfig.yml"
    config.write_text(KUBE_CONFIG_CONTENT)
    assert resolve_reference(f"file:{config}") == KUBE_CONFIG_CONTENT


def test_exec_takes_the_commands_stdout(tmp_path):
    config = tmp_path / "kubeconfig.yml"
    config.write_text(KUBE_CONFIG_CONTENT)
    assert resolve_reference(f"exec:cat {config}") == KUBE_CONFIG_CONTENT


def test_unset_variable_names_itself(monkeypatch, capsys):
    monkeypatch.delenv("KUBECONFIG_DATA", raising=False)
    with pytest.raises(SystemExit):
        resolve_reference("env:KUBECONFIG_DATA")
    # The variable is the thing the operator has to go and set, so it has to be
    # in the message: the reference alone leaves them guessing on a CI runner.
    assert "$KUBECONFIG_DATA is not set" in capsys.readouterr().err


def test_failing_command_carries_its_own_stderr(capsys):
    with pytest.raises(SystemExit):
        resolve_reference("exec:echo 'no such secret' >&2; exit 3")
    err = capsys.readouterr().err
    assert "exited 3" in err
    assert "no such secret" in err


def test_command_producing_nothing_is_an_error(capsys):
    # Silent success would otherwise reach the kubernetes client as an empty
    # config file, whose error says nothing about where it came from.
    with pytest.raises(SystemExit):
        resolve_reference("exec:true")
    assert "produced no output" in capsys.readouterr().err


# --- materialization ---------------------------------------------------------


def test_bare_path_uses_the_file_in_the_deployment_dir(tmp_path):
    with kube_config_file(FakeSpec("/home/me/.kube/config"), tmp_path) as path:
        assert path == tmp_path / "kubeconfig.yml"


def test_reference_materializes_outside_the_deployment_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("KUBECONFIG_DATA", KUBE_CONFIG_CONTENT)
    with kube_config_file(FakeSpec("env:KUBECONFIG_DATA"), tmp_path) as path:
        assert path.read_text() == KUBE_CONFIG_CONTENT
        assert tmp_path not in path.parents
        assert path.stat().st_mode & 0o077 == 0
        materialized = path
    # And nothing is left behind once the client has read it.
    assert not materialized.exists()
    assert not materialized.parent.exists()


def test_materialized_file_is_removed_even_when_the_caller_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("KUBECONFIG_DATA", KUBE_CONFIG_CONTENT)
    with pytest.raises(ValueError):
        with kube_config_file(FakeSpec("env:KUBECONFIG_DATA"), tmp_path) as path:
            materialized = path
            raise ValueError("load failed")
    assert not materialized.parent.exists()


# --- the deployment it produces ----------------------------------------------


def make_deployment(tmp_path, isolated_env, kube_config, env=None):
    """init + deploy a k8s deployment with the given kube-config value."""
    stack_dir = make_stack_from_compose(tmp_path, POD)
    spec_file = tmp_path / "spec.yml"
    deployment_dir = tmp_path / "deployment"

    result = run_stack(
        [
            "init",
            "--stack",
            str(stack_dir),
            "--deploy-to",
            "k8s",
            "--kube-config",
            kube_config,
            "--image-registry",
            "registry.example.com/org",
            "--output",
            str(spec_file),
        ],
        {**isolated_env, **(env or {})},
        cwd=tmp_path,
    )
    if result.returncode != 0:
        return result, None
    result = run_stack(
        ["deploy", "--spec-file", str(spec_file), "--deployment-dir", str(deployment_dir)],
        {**isolated_env, **(env or {})},
        cwd=tmp_path,
    )
    return result, deployment_dir


def test_a_referenced_credential_is_not_written_into_the_deployment(tmp_path, isolated_env):
    result, deployment_dir = make_deployment(tmp_path, isolated_env, "env:KUBECONFIG_DATA")

    assert result.returncode == 0, f"deploy failed:\n{result.stdout}\n{result.stderr}"
    # The point of the whole exercise: nothing to commit by accident.
    assert not (deployment_dir / "kubeconfig.yml").exists()
    # The reference does travel, so the deployment still knows where to look.
    assert "kube-config: env:KUBECONFIG_DATA" in (deployment_dir / "spec.yml").read_text()


def test_a_path_is_still_copied_in(tmp_path, isolated_env):
    config = tmp_path / "source-kubeconfig.yml"
    config.write_text(KUBE_CONFIG_CONTENT)

    result, deployment_dir = make_deployment(tmp_path, isolated_env, str(config))

    assert result.returncode == 0, f"deploy failed:\n{result.stdout}\n{result.stderr}"
    assert (deployment_dir / "kubeconfig.yml").read_text() == KUBE_CONFIG_CONTENT


def test_deploy_does_not_need_the_credential_to_be_resolvable(tmp_path, isolated_env):
    # Creating the deployment and connecting to the cluster happen on different
    # machines in the case this is for, so create time must not require the
    # secret to be present.
    result, _ = make_deployment(tmp_path, isolated_env, "exec:false")

    assert result.returncode == 0, f"deploy failed:\n{result.stdout}\n{result.stderr}"


def test_init_rejects_an_unknown_scheme(tmp_path, isolated_env):
    result, _ = make_deployment(tmp_path, isolated_env, "vault:secret/data/cluster")

    assert result.returncode != 0
    assert "unknown scheme 'vault:'" in (result.stdout + result.stderr)


def test_manage_resolves_the_reference(tmp_path, isolated_env):
    _, deployment_dir = make_deployment(tmp_path, isolated_env, "env:KUBECONFIG_DATA")

    # A syntactically valid kubeconfig naming no current context: enough to prove
    # the content was found and handed to the kubernetes client, without a cluster.
    result = run_stack(
        ["manage", "--dir", str(deployment_dir), "ps"],
        {**isolated_env, "KUBECONFIG_DATA": textwrap.dedent(KUBE_CONFIG_CONTENT)},
        cwd=tmp_path,
    )

    assert result.returncode != 0
    output = result.stdout + result.stderr
    assert "$KUBECONFIG_DATA is not set" not in output
    # The client's own complaint about the config it was given, which it can only
    # make if it received one.
    assert "context" in output.lower() or "current-context" in output.lower()
