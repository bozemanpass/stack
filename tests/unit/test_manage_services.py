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

"""Tests for `stack manage --dir <d> services`.

The command names the services the deployment runs, which is what its sibling
subcommands (start, logs, exec) take as an argument.  It reads them from the
deployment's own copies of the pod files: resolving the stack's pod list against
the stack search path instead used to crash for an old-format stack, whose bare
pod names found nothing in the deployment directory and fell through to the
builtin stacks (#257).
"""

from conftest import make_old_format_stack, make_stack_from_compose, run_stack


TWO_SERVICE_POD = """\
    services:
      database:
        image: postgres:16
      db-client:
        image: busybox:latest
    """

ONE_SERVICE_POD = """\
    services:
      web:
        image: nginx:latest
    """


def deploy(stack_dir, tmp_path, isolated_env, deployment_name="deployment"):
    spec_file = tmp_path / f"{deployment_name}-spec.yml"
    deployment_dir = tmp_path / deployment_name

    result = run_stack(
        ["init", "--stack", str(stack_dir), "--output", str(spec_file)],
        isolated_env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, f"init failed:\n{result.stdout}\n{result.stderr}"

    result = run_stack(
        ["deploy", "--spec-file", str(spec_file), "--deployment-dir", str(deployment_dir)],
        isolated_env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, f"deploy failed:\n{result.stdout}\n{result.stderr}"
    return deployment_dir


def services(deployment_dir, isolated_env, tmp_path):
    result = run_stack(["manage", "--dir", str(deployment_dir), "services"], isolated_env, cwd=tmp_path)
    assert result.returncode == 0, f"services failed:\n{result.stdout}\n{result.stderr}"
    return result.stdout.split()


def test_services_lists_an_old_format_stacks_services(tmp_path, isolated_env):
    stack_dir = make_old_format_stack(tmp_path, {"db": TWO_SERVICE_POD})
    deployment_dir = deploy(stack_dir, tmp_path, isolated_env)
    assert services(deployment_dir, isolated_env, tmp_path) == ["database", "db-client"]


def test_services_lists_a_new_format_stacks_services(tmp_path, isolated_env):
    stack_dir = make_stack_from_compose(tmp_path, ONE_SERVICE_POD)
    deployment_dir = deploy(stack_dir, tmp_path, isolated_env)
    assert services(deployment_dir, isolated_env, tmp_path) == ["web"]


def test_services_covers_every_pod_of_a_multi_pod_stack(tmp_path, isolated_env):
    # Sorted, and drawn from every pod file in the deployment -- which is what
    # makes the list usable as the argument to `manage logs` and friends.
    stack_dir = make_old_format_stack(tmp_path, {"db": TWO_SERVICE_POD, "front": ONE_SERVICE_POD})
    deployment_dir = deploy(stack_dir, tmp_path, isolated_env)
    assert services(deployment_dir, isolated_env, tmp_path) == ["database", "db-client", "web"]
