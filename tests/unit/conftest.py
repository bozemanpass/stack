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


def make_stack_from_compose(base_dir, compose_yaml, name="teststack", stack_yaml=None):
    """Create a stack whose single pod has the given (dedented) composefile content.

    Unlike make_stack_fixture this places no constraints on the compose content, so
    tests can exercise volumes, healthchecks, env files and the like.
    """
    stack_dir = base_dir / name
    pod_dir = stack_dir / "web"
    pod_dir.mkdir(parents=True)
    if stack_yaml is None:
        stack_yaml = textwrap.dedent(
            f"""\
            name: {name}
            description: "test stack"
            pods:
              - name: web
                path: ./web
            """
        )
    (stack_dir / "stack.yml").write_text(stack_yaml)
    (pod_dir / "composefile.yml").write_text(textwrap.dedent(compose_yaml))
    subprocess.run(["git", "init", "-q", str(stack_dir)], check=True)
    subprocess.run(
        ["git", "-C", str(stack_dir), "remote", "add", "origin", f"https://github.com/example/{name}.git"],
        check=True,
    )
    return stack_dir


def make_multi_pod_stack(base_dir, pod_composefiles, name="multipodstack"):
    """Create a stack with one pod per entry in {pod name: composefile content}.

    Pods are declared in the order given, which is what a caller testing order
    sensitivity needs to control.
    """
    stack_dir = base_dir / name
    for pod_name, compose_yaml in pod_composefiles.items():
        pod_dir = stack_dir / pod_name
        pod_dir.mkdir(parents=True)
        (pod_dir / "composefile.yml").write_text(textwrap.dedent(compose_yaml))
    pods_yaml = "".join(f"  - name: {pod_name}\n    path: ./{pod_name}\n" for pod_name in pod_composefiles)
    (stack_dir / "stack.yml").write_text(f"name: {name}\ndescription: \"test stack\"\npods:\n{pods_yaml}")
    subprocess.run(["git", "init", "-q", str(stack_dir)], check=True)
    subprocess.run(
        ["git", "-C", str(stack_dir), "remote", "add", "origin", f"https://github.com/example/{name}.git"],
        check=True,
    )
    return stack_dir


# A cluster id is normally a random token, which would make the generated object
# content (app labels, salted image tags) unassertable.  Tests pin it instead.
TEST_CLUSTER_ID = "stack-0123456789abcdef"


def make_cluster_info(tmp_path, compose_yaml, spec_obj, deployment_name=TEST_CLUSTER_ID):
    """Build a ClusterInfo over one pod file, for testing k8s object generation.

    Requires no cluster and no kubeconfig: ClusterInfo only parses the pod files and
    the spec.  The pod file is written to disk and loaded through the same YAML path
    the real deployer uses, so comment- and sequence-typed content behaves identically.
    """
    # Imported here rather than at module scope so that collecting this file does not
    # require the kubernetes client.
    from stack.deploy.spec import Spec
    from stack.deploy.k8s.cluster_info import ClusterInfo

    pod_file = tmp_path / "compose-web.yml"
    pod_file.write_text(textwrap.dedent(compose_yaml))
    spec = Spec(file_path=tmp_path / "spec.yml", obj=spec_obj)
    cluster_info = ClusterInfo()
    # The env file need not exist; a missing one yields no shared environment.
    cluster_info.int([str(pod_file)], tmp_path / "config.env", deployment_name, spec)
    return cluster_info


def k8s_dict(obj):
    """Serialize a kubernetes client object the same way the API client would.

    This is the transformation that turns the in-memory objects into what actually
    goes over the wire, so asserting on its output tests what the cluster would see.
    """
    from kubernetes import client

    return client.ApiClient().sanitize_for_serialization(obj)


def make_old_format_stack(base_dir, pod_composefiles, name="oldformatstack"):
    """Create an old-format stack -- pods named as bare strings -- and return its path.

    The pod files of such a stack are not next to the stack.yml: they are found by
    name in the repo's shared `compose` directory, which is what the layout below
    reproduces (and is why the git repo is the outer directory, not the stack's).
    """
    repo_dir = base_dir / f"{name}-repo"
    stack_dir = repo_dir / "stack-files" / "stacks" / name
    compose_dir = repo_dir / "stack-files" / "compose"
    stack_dir.mkdir(parents=True)
    compose_dir.mkdir(parents=True)
    for pod_name, compose_yaml in pod_composefiles.items():
        (compose_dir / f"composefile-{pod_name}.yml").write_text(textwrap.dedent(compose_yaml))
    pods_yaml = "".join(f"  - {pod_name}\n" for pod_name in pod_composefiles)
    (stack_dir / "stack.yml").write_text(f"name: {name}\ndescription: \"test stack\"\npods:\n{pods_yaml}")
    subprocess.run(["git", "init", "-q", str(repo_dir)], check=True)
    subprocess.run(
        ["git", "-C", str(repo_dir), "remote", "add", "origin", f"https://github.com/example/{name}.git"],
        check=True,
    )
    return stack_dir
