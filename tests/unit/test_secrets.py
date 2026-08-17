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

"""Secrets a stack declares, injected at deploy time rather than recorded.

The property under test throughout is the one the feature exists for: no secret
value in spec.yml, config.env, or a generated compose file -- a generated value
lives only in a 0600, gitignored secrets.env (or, on a remote cluster, in the
cluster), and a referenced value is never persisted at all.
"""

import re
import textwrap

import pytest

from conftest import make_stack_from_compose, make_cluster_info, k8s_dict, run_stack

from stack.deploy.secrets import (
    GENERATE,
    K8S_SECRET_NAME,
    ensure_generated_secrets,
    resolve_referenced_secrets,
    shell_var,
    validate_secret_entry,
)
from stack.deploy.spec import Spec


# A pod whose author declared POSTGRES_PASSWORD secret but left the old literal
# default behind in the compose file -- the migration case, and the one where a
# leftover would silently override the injected value.
POD_WITH_LITERAL = """\
    services:
      db:
        image: postgres:local
        environment:
          POSTGRES_USER: "test-user"
          POSTGRES_PASSWORD: "cleartext-default"
        ports:
          - "5432"
      client:
        image: client:local
    """


def stack_yaml(name, secrets_yaml):
    return (
        textwrap.dedent(
            f"""\
            name: {name}
            description: "test stack"
            pods:
              - name: web
                path: ./web
            """
        )
        + secrets_yaml
    )


def make_secret_stack(tmp_path, secrets_yaml="secrets:\n  POSTGRES_PASSWORD:\n", name="secretstack", pod=POD_WITH_LITERAL):
    return make_stack_from_compose(tmp_path, pod, name=name, stack_yaml=stack_yaml(name, secrets_yaml))


def run_init(tmp_path, isolated_env, stack_dir, *extra_args):
    spec_file = tmp_path / "spec.yml"
    result = run_stack(
        ["init", "--stack", str(stack_dir), "--output", str(spec_file), *extra_args],
        isolated_env,
        cwd=tmp_path,
    )
    return result, spec_file


def make_deployment(tmp_path, isolated_env, stack_dir, *extra_init_args):
    result, spec_file = run_init(tmp_path, isolated_env, stack_dir, *extra_init_args)
    assert result.returncode == 0, f"init failed:\n{result.stdout}\n{result.stderr}"
    deployment_dir = tmp_path / "deployment"
    result = run_stack(
        ["deploy", "--spec-file", str(spec_file), "--deployment-dir", str(deployment_dir)],
        isolated_env,
        cwd=tmp_path,
    )
    return result, deployment_dir


# --- what a spec secrets entry may say ---------------------------------------


def test_generate_and_references_are_valid():
    validate_secret_entry("PW", GENERATE)
    validate_secret_entry("PW", "env:PW_DATA")
    validate_secret_entry("PW", "exec:pass show db")


def test_a_literal_value_is_rejected(capsys):
    # The whole point is that values never sit in the spec, so a value that is
    # neither `generate` nor a reference has to be refused, not stored.
    with pytest.raises(SystemExit):
        validate_secret_entry("PW", "hunter2")
    assert "never stored in the spec" in capsys.readouterr().err


def test_an_unknown_scheme_is_rejected(capsys):
    with pytest.raises(SystemExit):
        validate_secret_entry("PW", "vault:secret/db")
    assert "unknown scheme 'vault:'" in capsys.readouterr().err


# --- generated values ---------------------------------------------------------


def spec_with_secrets(entries):
    return Spec(obj={"secrets": entries})


def test_generated_secrets_are_minted_once_and_kept(tmp_path):
    spec = spec_with_secrets({"PW": GENERATE})
    first = ensure_generated_secrets(spec, tmp_path)
    assert re.fullmatch(r"[0-9a-f]{32}", first["PW"])
    # Create-or-keep: the value a data volume depends on must never rotate.
    assert ensure_generated_secrets(spec, tmp_path)["PW"] == first["PW"]

    secrets_env = tmp_path / "secrets.env"
    assert f"PW={first['PW']}" in secrets_env.read_text()
    assert secrets_env.stat().st_mode & 0o077 == 0
    # A deployment directory is frequently a git repository.
    assert "secrets.env" in (tmp_path / ".gitignore").read_text().splitlines()


def test_a_missing_secret_is_minted_without_touching_the_others(tmp_path):
    first = ensure_generated_secrets(spec_with_secrets({"PW": GENERATE}), tmp_path)
    both = ensure_generated_secrets(spec_with_secrets({"PW": GENERATE, "TOKEN": GENERATE}), tmp_path)
    assert both["PW"] == first["PW"]
    assert re.fullmatch(r"[0-9a-f]{32}", both["TOKEN"])


def test_referenced_secrets_resolve_from_the_environment(monkeypatch):
    monkeypatch.setenv("PW_DATA", "s3cret")
    spec = spec_with_secrets({"PW": "env:PW_DATA", "GEN": GENERATE})
    # Only the reference resolves here; generated values have their own store.
    assert resolve_referenced_secrets(spec) == {"PW": "s3cret"}


# --- init records provenance, not values --------------------------------------


def test_a_declared_secret_defaults_to_generate(tmp_path, isolated_env):
    result, spec_file = run_init(tmp_path, isolated_env, make_secret_stack(tmp_path))
    assert result.returncode == 0, f"init failed:\n{result.stdout}\n{result.stderr}"
    assert "POSTGRES_PASSWORD: generate" in spec_file.read_text()


def test_an_external_secret_requires_a_reference(tmp_path, isolated_env):
    stack_dir = make_secret_stack(tmp_path, "secrets:\n  API_KEY:\n    external: true\n")
    result, _ = run_init(tmp_path, isolated_env, stack_dir)
    assert result.returncode != 0
    assert "API_KEY" in (result.stdout + result.stderr)

    result, spec_file = run_init(tmp_path, isolated_env, stack_dir, "--secret", "API_KEY=env:API_KEY_DATA")
    assert result.returncode == 0, f"init failed:\n{result.stdout}\n{result.stderr}"
    assert "API_KEY: env:API_KEY_DATA" in spec_file.read_text()


def test_init_rejects_a_secret_value(tmp_path, isolated_env):
    result, _ = run_init(tmp_path, isolated_env, make_secret_stack(tmp_path), "--secret", "POSTGRES_PASSWORD=hunter2")
    assert result.returncode != 0
    assert "never stored in the spec" in (result.stdout + result.stderr)


def test_a_key_cannot_be_both_config_and_secret(tmp_path, isolated_env):
    result, _ = run_init(tmp_path, isolated_env, make_secret_stack(tmp_path), "--config", "POSTGRES_PASSWORD=hunter2")
    assert result.returncode != 0
    assert "may not also be set with --config" in (result.stdout + result.stderr)


# --- the compose deployment it produces ---------------------------------------


def test_a_compose_deployment_holds_no_cleartext_secret(tmp_path, isolated_env):
    result, deployment_dir = make_deployment(tmp_path, isolated_env, make_secret_stack(tmp_path))
    assert result.returncode == 0, f"deploy failed:\n{result.stdout}\n{result.stderr}"

    compose_file = (deployment_dir / "compose" / "composefile-web.yml").read_text()
    # The stack file's literal default must not survive into the deployment.
    assert "cleartext-default" not in compose_file
    assert "POSTGRES_PASSWORD" not in (deployment_dir / "config.env").read_text()
    assert "generate" in (deployment_dir / "spec.yml").read_text()

    # Every service reads the minted value from secrets.env, like config.env.
    assert compose_file.count("secrets.env") == 2
    secrets_env = deployment_dir / "secrets.env"
    assert re.search(r"POSTGRES_PASSWORD=[0-9a-f]{32}", secrets_env.read_text())
    assert secrets_env.stat().st_mode & 0o077 == 0
    assert "secrets.env" in (deployment_dir / ".gitignore").read_text().splitlines()


def test_a_referenced_secret_is_interpolated_not_persisted(tmp_path, isolated_env):
    stack_dir = make_secret_stack(tmp_path, "secrets:\n  API_KEY:\n    external: true\n")
    result, deployment_dir = make_deployment(tmp_path, isolated_env, stack_dir, "--secret", "API_KEY=env:API_KEY_DATA")
    assert result.returncode == 0, f"deploy failed:\n{result.stdout}\n{result.stderr}"

    compose_file = (deployment_dir / "compose" / "composefile-web.yml").read_text()
    # The compose file consumes a variable the deployer exports at up time...
    assert f"${{{shell_var('API_KEY')}:-}}" in compose_file
    # ...and with no generated secrets, nothing warranted a secrets.env at all.
    assert not (deployment_dir / "secrets.env").exists()


def test_deploy_rejects_a_hand_edited_literal(tmp_path, isolated_env):
    result, spec_file = run_init(tmp_path, isolated_env, make_secret_stack(tmp_path))
    assert result.returncode == 0
    spec_file.write_text(spec_file.read_text().replace("POSTGRES_PASSWORD: generate", "POSTGRES_PASSWORD: hunter2"))
    result = run_stack(
        ["deploy", "--spec-file", str(spec_file), "--deployment-dir", str(tmp_path / "deployment")],
        isolated_env,
        cwd=tmp_path,
    )
    assert result.returncode != 0
    assert "never stored in the spec" in (result.stdout + result.stderr)


# --- inspecting a deployment's secrets ----------------------------------------


def run_manage_secrets(deployment_dir, isolated_env, *args, env=None):
    return run_stack(["manage", "--dir", str(deployment_dir), "secrets", *args], {**isolated_env, **(env or {})})


def test_list_names_provenance_but_no_values(tmp_path, isolated_env):
    _, deployment_dir = make_deployment(tmp_path, isolated_env, make_secret_stack(tmp_path))
    result = run_manage_secrets(deployment_dir, isolated_env, "list")
    assert result.returncode == 0, f"list failed:\n{result.stdout}\n{result.stderr}"
    assert "POSTGRES_PASSWORD\tgenerate" in result.stdout
    minted = re.search(r"POSTGRES_PASSWORD=([0-9a-f]{32})", (deployment_dir / "secrets.env").read_text()).group(1)
    assert minted not in result.stdout


def test_show_reveals_the_minted_value(tmp_path, isolated_env):
    _, deployment_dir = make_deployment(tmp_path, isolated_env, make_secret_stack(tmp_path))
    minted = re.search(r"POSTGRES_PASSWORD=([0-9a-f]{32})", (deployment_dir / "secrets.env").read_text()).group(1)
    result = run_manage_secrets(deployment_dir, isolated_env, "show")
    assert result.returncode == 0, f"show failed:\n{result.stdout}\n{result.stderr}"
    assert f"POSTGRES_PASSWORD={minted}" in result.stdout


def test_show_resolves_a_referenced_secret(tmp_path, isolated_env):
    stack_dir = make_secret_stack(tmp_path, "secrets:\n  API_KEY:\n    external: true\n")
    _, deployment_dir = make_deployment(tmp_path, isolated_env, stack_dir, "--secret", "API_KEY=env:API_KEY_DATA")

    result = run_manage_secrets(deployment_dir, isolated_env, "show", "API_KEY", env={"API_KEY_DATA": "s3cret"})
    assert result.returncode == 0, f"show failed:\n{result.stdout}\n{result.stderr}"
    assert "API_KEY=s3cret" in result.stdout

    # The same failure the next up would give, at a moment it is cheap to see.
    result = run_manage_secrets(deployment_dir, isolated_env, "show", "API_KEY")
    assert result.returncode != 0
    assert "$API_KEY_DATA is not set" in (result.stdout + result.stderr)


def test_show_rejects_an_unknown_name(tmp_path, isolated_env):
    _, deployment_dir = make_deployment(tmp_path, isolated_env, make_secret_stack(tmp_path))
    result = run_manage_secrets(deployment_dir, isolated_env, "show", "NO_SUCH_SECRET")
    assert result.returncode != 0
    assert "no such secret: NO_SUCH_SECRET" in (result.stdout + result.stderr)


def test_show_on_kind_needs_no_cluster(tmp_path, isolated_env):
    # On kind the deployment directory is the store precisely because stopping
    # the deployment destroys the cluster -- so inspection works stopped, too.
    _, deployment_dir = make_deployment(tmp_path, isolated_env, make_secret_stack(tmp_path), "--deploy-to", "k8s-kind")
    minted = re.search(r"POSTGRES_PASSWORD=([0-9a-f]{32})", (deployment_dir / "secrets.env").read_text()).group(1)
    result = run_manage_secrets(deployment_dir, isolated_env, "show")
    assert result.returncode == 0, f"show failed:\n{result.stdout}\n{result.stderr}"
    assert f"POSTGRES_PASSWORD={minted}" in result.stdout


def test_a_stack_without_secrets_says_so(tmp_path, isolated_env):
    stack_dir = make_stack_from_compose(tmp_path, POD_WITH_LITERAL, name="plainstack")
    _, deployment_dir = make_deployment(tmp_path, isolated_env, stack_dir)
    for subcommand in ("list", "show"):
        result = run_manage_secrets(deployment_dir, isolated_env, subcommand)
        assert result.returncode == 0, f"{subcommand} failed:\n{result.stdout}\n{result.stderr}"
        assert "No secrets" in result.stdout


# --- the k8s objects it produces ----------------------------------------------


def test_k8s_containers_reference_the_secret_not_the_value(tmp_path):
    cluster_info = make_cluster_info(
        tmp_path,
        POD_WITH_LITERAL,
        {"stack": "secretstack", "deploy-to": "k8s-kind", "secrets": {"POSTGRES_PASSWORD": GENERATE}},
    )
    for deployment in cluster_info.get_deployments():
        container = k8s_dict(deployment)["spec"]["template"]["spec"]["containers"][0]
        envs = {env["name"]: env for env in container.get("env", [])}
        # Every container gets the secret -- the client as much as the database.
        secret_env = envs["POSTGRES_PASSWORD"]
        assert "value" not in secret_env
        assert secret_env["valueFrom"]["secretKeyRef"] == {"name": K8S_SECRET_NAME, "key": "POSTGRES_PASSWORD"}
    # And the literal default is nowhere in any generated object.
    assert "cleartext-default" not in str([k8s_dict(d) for d in cluster_info.get_deployments()])
