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

"""Tests for `stack manage --dir <d> destroy` and what stop no longer does.

Stop is the symmetric opposite of start and deletes nothing that start cannot
make again; destroy is the signal that a deployment is finished (#287).  These
cover the parts of that split which need no engine: the retired stop flag, the
confirmation, and the marker that keeps the rest of `manage` from operating on a
deployment whose objects are gone.
"""

from conftest import make_stack_from_compose, run_stack

from stack import constants


ONE_SERVICE_POD = """\
    services:
      web:
        image: nginx:latest
    """


def deploy(tmp_path, isolated_env):
    stack_dir = make_stack_from_compose(tmp_path, ONE_SERVICE_POD)
    spec_file = tmp_path / "spec.yml"
    deployment_dir = tmp_path / "deployment"

    result = run_stack(["init", "--stack", str(stack_dir), "--output", str(spec_file)], isolated_env, cwd=tmp_path)
    assert result.returncode == 0, f"init failed:\n{result.stdout}\n{result.stderr}"
    result = run_stack(
        ["deploy", "--spec-file", str(spec_file), "--deployment-dir", str(deployment_dir)],
        isolated_env,
        cwd=tmp_path,
    )
    assert result.returncode == 0, f"deploy failed:\n{result.stdout}\n{result.stderr}"
    return deployment_dir


def manage(deployment_dir, args, isolated_env, tmp_path):
    return run_stack(["manage", "--dir", str(deployment_dir)] + args, isolated_env, cwd=tmp_path)


def mark_destroyed(deployment_dir):
    """What destroy leaves behind, without needing an engine to reach it."""
    marker = deployment_dir.joinpath(constants.destroyed_file_name)
    marker.write_text("destroyed 2026-08-20T00:00:00+00:00\n")
    return marker


def test_stop_refuses_delete_volumes_rather_than_ignoring_it(tmp_path, isolated_env):
    # Silently accepting the retired flag would leak exactly the volumes the
    # caller asked to reclaim, so it fails loudly and names its replacement.
    deployment_dir = deploy(tmp_path, isolated_env)
    result = manage(deployment_dir, ["stop", "--delete-volumes"], isolated_env, tmp_path)

    assert result.returncode != 0
    assert "destroy" in result.stdout + result.stderr


def test_destroy_asks_before_it_destroys(tmp_path, isolated_env):
    deployment_dir = deploy(tmp_path, isolated_env)
    result = manage(deployment_dir, ["destroy"], isolated_env, tmp_path)

    # No answer on a closed stdin is not an answer, so nothing happened.
    assert result.returncode != 0
    assert not deployment_dir.joinpath(constants.destroyed_file_name).exists()


def test_a_destroyed_deployment_is_refused_by_the_other_subcommands(tmp_path, isolated_env):
    deployment_dir = deploy(tmp_path, isolated_env)
    mark_destroyed(deployment_dir)

    result = manage(deployment_dir, ["services"], isolated_env, tmp_path)
    assert result.returncode != 0
    assert "destroyed" in result.stdout + result.stderr


def test_destroy_still_runs_against_an_already_destroyed_deployment(tmp_path, isolated_env):
    # An interrupted destroy has to be repeatable, so the marker does not lock
    # the one command that could finish the job.
    deployment_dir = deploy(tmp_path, isolated_env)
    mark_destroyed(deployment_dir)

    result = manage(deployment_dir, ["destroy", "--help"], isolated_env, tmp_path)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    assert "--delete-certificate" in result.stdout
