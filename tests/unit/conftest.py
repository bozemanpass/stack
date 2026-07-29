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

import os
import subprocess
import sys
import textwrap

import pytest


@pytest.fixture
def isolated_env(tmp_path):
    """Environment for running the CLI isolated from the developer's real
    stack config (~/.config/stack) and any STACK_* environment settings."""
    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("STACK_")}
    env["HOME"] = str(home)
    return env


def run_stack(args, env, cwd=None):
    """Run the stack CLI in a subprocess, returning CompletedProcess.

    A subprocess (rather than click's CliRunner) is required because some CLI
    option defaults read the config profile at module import time.
    """
    return subprocess.run(
        [sys.executable, "-m", "stack"] + args,
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def make_stack_fixture(base_dir, name="teststack", ports_yaml='      - "80"\n'):
    """Create a minimal single-pod stack in a local git checkout and return its path.

    The directory must look like a git clone with a remote so that stack.yml
    resolution and pod-file lookup work.
    """
    stack_dir = base_dir / name
    pod_dir = stack_dir / "web"
    pod_dir.mkdir(parents=True)
    (stack_dir / "stack.yml").write_text(
        textwrap.dedent(
            f"""\
            name: {name}
            description: "minimal test stack"
            pods:
              - name: web
                path: ./web
            """
        )
    )
    (pod_dir / "composefile.yml").write_text(
        "services:\n" "  web:\n" "    image: nginx:latest\n" "    ports:\n" + ports_yaml
    )
    subprocess.run(["git", "init", "-q", str(stack_dir)], check=True)
    subprocess.run(
        ["git", "-C", str(stack_dir), "remote", "add", "origin", f"https://github.com/example/{name}.git"],
        check=True,
    )
    return stack_dir


@pytest.fixture
def minimal_stack(tmp_path):
    """A stack whose service exposes a port with no http-proxy annotation."""
    return make_stack_fixture(tmp_path)


@pytest.fixture
def annotated_stack(tmp_path):
    """A stack whose service port carries an http-proxy annotation."""
    return make_stack_fixture(tmp_path, name="annotatedstack", ports_yaml='      - "80"  # @stack http-proxy /\n')
