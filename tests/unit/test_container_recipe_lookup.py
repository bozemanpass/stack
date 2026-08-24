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

"""Tests for finding a container's build recipe (issue #297).

A stack's colocated containers -- those with no `ref` of their own, whose recipes sit
beside it in its own repo -- have to be found in the tree the stack was loaded from.
Looking for them under the dev root instead finds nothing when the stack came from a
working checkout, and the miss is silent: the build falls through to the default build
with the repo root as its context and fails on a Dockerfile that was never involved.
"""

import subprocess
import textwrap

from pathlib import Path

import pytest

from stack.build.build_containers import process_container
from stack.build.build_types import BuildContext
from stack.build.build_util import compute_image_identity, get_containers_in_scope
from stack.command_types import CommandOptions
from stack.deploy.stack import Stack
from stack.opts import opts


DEFAULT_CONTAINER_BASE_DIR = Path(__file__).absolute().parent.parent.parent.joinpath(
    "src", "stack", "data", "container-build"
)


def make_checkout(base_dir, origin, with_recipe=True, name="teststack"):
    """A repo laid out the way a stack repo is: stacks and container recipes side by side.

    `origin` is the remote the checkout is given, since whether a repo ref can be derived
    from it is the thing under test.  Returns the stack's directory.
    """
    repo_dir = base_dir / "checkout"
    stack_dir = repo_dir / "stack-files" / "stacks" / name
    pod_dir = stack_dir / "web"
    pod_dir.mkdir(parents=True)
    (stack_dir / "stack.yml").write_text(
        textwrap.dedent(
            f"""\
            name: {name}
            description: "test stack"
            containers:
              - example/web
            pods:
              - name: web
                path: ./web
            """
        )
    )
    (pod_dir / "composefile.yml").write_text("services:\n  web:\n    image: example/web:stack\n")
    if with_recipe:
        recipe_dir = repo_dir / "stack-files" / "containers" / "example-web"
        recipe_dir.mkdir(parents=True)
        (recipe_dir / "build.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    subprocess.run(["git", "init", "-q", str(repo_dir)], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "remote", "add", "origin", origin], check=True)
    subprocess.run(["git", "-C", str(repo_dir), "add", "-A"], check=True)
    # An image's identity is the recipe repo's commit hash, so the checkout needs one.
    subprocess.run(["git", "-C", str(repo_dir), "-c", "user.email=test@example.com",
                    "-c", "user.name=test", "commit", "-q", "-m", "initial"], check=True)
    return stack_dir


def resolve_build(stack_dir, dev_root):
    """Run the build of the stack's one container as a dry run, returning its environment.

    The build environment is where the resolved recipe directory shows up: STACK_BUILD_DIR
    is the directory the build script was found in, or the default build's context when no
    script was found.
    """
    stack = Stack().init_from_file(stack_dir / "stack.yml")
    stack_container = get_containers_in_scope(stack)[0]
    identity = compute_image_identity(stack, stack_container, dev_root)
    build_env = {}
    context = BuildContext(stack, identity.container_spec, DEFAULT_CONTAINER_BASE_DIR, build_env, dev_root)
    assert process_container(context)
    return build_env


@pytest.fixture(autouse=True)
def dry_run_opts():
    """Resolve the build without running it: the recipe lookup is what is under test."""
    saved = opts.o
    opts.o = CommandOptions(dry_run=True)
    yield
    opts.o = saved


def test_colocated_recipe_found_in_local_checkout(tmp_path):
    # The repo is not under the dev root -- which is what standing in a working checkout
    # (or a CI actions/checkout) looks like -- so only the checkout can supply the recipe.
    stack_dir = make_checkout(tmp_path, "https://github.com/example/teststack.git")
    build_env = resolve_build(stack_dir, tmp_path / "empty-dev-root")
    assert Path(build_env["STACK_BUILD_DIR"]) == tmp_path / "checkout" / "stack-files" / "containers" / "example-web"


def test_colocated_recipe_found_when_no_repo_ref_can_be_derived(tmp_path):
    # A checkout whose origin is a local path names no repo we can resolve, so there is
    # no ref to look up at all.  The checkout is still all the recipe can be in.
    stack_dir = make_checkout(tmp_path, str(tmp_path / "upstream.git"))
    build_env = resolve_build(stack_dir, tmp_path / "empty-dev-root")
    assert Path(build_env["STACK_BUILD_DIR"]) == tmp_path / "checkout" / "stack-files" / "containers" / "example-web"


def test_missing_recipe_still_falls_back_to_the_default_build(tmp_path):
    # No recipe anywhere: the default build gets the repo as its context, as before.
    stack_dir = make_checkout(tmp_path, "https://github.com/example/teststack.git", with_recipe=False)
    build_env = resolve_build(stack_dir, tmp_path / "empty-dev-root")
    assert Path(build_env["STACK_BUILD_DIR"]) == tmp_path / "checkout"
