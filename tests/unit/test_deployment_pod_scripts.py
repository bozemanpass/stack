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

"""The deployment directory's `pods/` tree.

It holds one thing: the pre/post-start scripts of the pods that declare them,
copied in at deploy time because a deployment reads nothing from the stack it
came from.  `manage start` runs them from there (deploy.py builds the path as
<deployment>/pods/<pod>/scripts/<basename>), so the layout below is a contract
between the two, not an implementation detail of either.

Every pod used to get a directory whether it had scripts or not, which left an
empty pods/<pod> beside most deployments and no way to tell what it was for
(#128).
"""

import subprocess
import textwrap

import pytest

from conftest import run_stack


POD_COMPOSE = """\
    services:
      web:
        image: nginx:latest
    """


def make_hook_stack(dev_root, pre_start=None, post_start=None, name="hookstack"):
    """A stack whose single pod optionally declares start hooks.

    Written into the dev root under its repo ref, because that is where the script
    paths are resolved from (stack.py get_pod_script_paths).
    """
    stack_dir = dev_root / "github.com" / "example" / name
    pod_dir = stack_dir / "web"
    pod_dir.mkdir(parents=True)
    (pod_dir / "composefile.yml").write_text(textwrap.dedent(POD_COMPOSE))
    hooks = ""
    for key, script in (("pre_start_command", pre_start), ("post_start_command", post_start)):
        if script:
            (pod_dir / script).write_text("#!/usr/bin/env bash\ntrue\n")
            hooks += f"    {key}: {script}\n"
    (stack_dir / "stack.yml").write_text(
        f"name: {name}\ndescription: \"test stack\"\npods:\n  - name: web\n    path: ./web\n{hooks}"
    )
    subprocess.run(["git", "init", "-q", str(stack_dir)], check=True)
    subprocess.run(
        ["git", "-C", str(stack_dir), "remote", "add", "origin", f"https://github.com/example/{name}.git"],
        check=True,
    )
    return stack_dir


@pytest.fixture
def dev_root(tmp_path, isolated_env):
    """A repo base dir the CLI will resolve pod script paths against."""
    root = tmp_path / "repos"
    root.mkdir()
    isolated_env["STACK_REPO_BASE_DIR"] = str(root)
    return root


def deploy(stack_dir, tmp_path, isolated_env):
    spec_file = tmp_path / "spec.yml"
    deployment_dir = tmp_path / "deployment"
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


def test_pod_start_scripts_are_copied_into_the_deployment(tmp_path, isolated_env, dev_root):
    stack_dir = make_hook_stack(dev_root, pre_start="pre_start.sh", post_start="post_start.sh")
    deployment_dir = deploy(stack_dir, tmp_path, isolated_env)

    script_dir = deployment_dir / "pods" / "web" / "scripts"
    assert sorted(p.name for p in script_dir.iterdir()) == ["post_start.sh", "pre_start.sh"]


def test_only_the_declared_script_is_copied(tmp_path, isolated_env, dev_root):
    stack_dir = make_hook_stack(dev_root, post_start="post_start.sh")
    deployment_dir = deploy(stack_dir, tmp_path, isolated_env)

    script_dir = deployment_dir / "pods" / "web" / "scripts"
    assert [p.name for p in script_dir.iterdir()] == ["post_start.sh"]


def test_a_stack_without_start_hooks_gets_no_pods_directory(tmp_path, isolated_env, dev_root):
    stack_dir = make_hook_stack(dev_root)
    deployment_dir = deploy(stack_dir, tmp_path, isolated_env)

    assert not (deployment_dir / "pods").exists()
