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

"""Tests for `stack validate`: the referential-integrity join between what a stack's
pod files import (image: lines with a locally built tag) and what its stack.yml
declares (containers: entries), plus the deprecation warnings for the legacy
`repos:` list and per-pod `repository:` field."""

import textwrap

from conftest import make_stack_from_compose, run_stack


def validate(stack_dir, env, *extra_args):
    return run_stack(["validate", "--stack", str(stack_dir)] + list(extra_args), env)


def make_stack(tmp_path, compose_yaml, stack_yaml=None, name="teststack"):
    return make_stack_from_compose(tmp_path, compose_yaml, name=name, stack_yaml=stack_yaml)


CLEAN_STACK_YAML = """\
    name: teststack
    description: "test stack"
    containers:
      - bozemanpass/web
    pods:
      - name: web
        path: ./web
    """

CLEAN_COMPOSE_YAML = """\
    services:
      web:
        image: bozemanpass/web:stack
      db:
        image: postgres:14
    """


def test_clean_stack_validates_ok(tmp_path, isolated_env):
    stack_dir = make_stack(tmp_path, CLEAN_COMPOSE_YAML, textwrap.dedent(CLEAN_STACK_YAML))
    result = validate(stack_dir, isolated_env)
    assert result.returncode == 0
    assert "teststack: OK" in result.stdout


def test_undeclared_container_is_an_error(tmp_path, isolated_env):
    # The pod imports bozemanpass/api:stack but the stack declares no such container.
    stack_dir = make_stack(
        tmp_path,
        """\
        services:
          web:
            image: bozemanpass/web:stack
          api:
            image: bozemanpass/api:stack
        """,
        textwrap.dedent(CLEAN_STACK_YAML),
    )
    result = validate(stack_dir, isolated_env)
    assert result.returncode == 1
    assert "container-undeclared" in result.stdout
    assert "bozemanpass/api" in result.stdout


def test_unused_container_declaration_is_a_warning(tmp_path, isolated_env):
    stack_dir = make_stack(
        tmp_path,
        CLEAN_COMPOSE_YAML,
        textwrap.dedent(
            """\
            name: teststack
            description: "test stack"
            containers:
              - bozemanpass/web
              - bozemanpass/orphan
            pods:
              - name: web
                path: ./web
            """
        ),
    )
    result = validate(stack_dir, isolated_env)
    # A warning alone passes...
    assert result.returncode == 0
    assert "container-unused" in result.stdout
    assert "bozemanpass/orphan" in result.stdout
    # ...unless --strict promotes it.
    assert validate(stack_dir, isolated_env, "--strict").returncode == 1


def test_image_interpolation_is_an_error(tmp_path, isolated_env):
    stack_dir = make_stack(
        tmp_path,
        """\
        services:
          web:
            image: ${WEB_IMAGE}
        """,
        textwrap.dedent(
            """\
            name: teststack
            description: "test stack"
            pods:
              - name: web
                path: ./web
            """
        ),
    )
    result = validate(stack_dir, isolated_env)
    assert result.returncode == 1
    assert "image-interpolation" in result.stdout


def test_untagged_external_image_is_a_warning(tmp_path, isolated_env):
    stack_dir = make_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx
        """,
        textwrap.dedent(
            """\
            name: teststack
            description: "test stack"
            pods:
              - name: web
                path: ./web
            """
        ),
    )
    result = validate(stack_dir, isolated_env)
    assert result.returncode == 0
    assert "external-image-untagged" in result.stdout


def test_digest_pinned_external_image_is_not_flagged(tmp_path, isolated_env):
    stack_dir = make_stack(
        tmp_path,
        """\
        services:
          web:
            image: nginx@sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
        """,
        textwrap.dedent(
            """\
            name: teststack
            description: "test stack"
            pods:
              - name: web
                path: ./web
            """
        ),
    )
    result = validate(stack_dir, isolated_env)
    assert result.returncode == 0
    assert "teststack: OK" in result.stdout


def test_repos_list_is_deprecated(tmp_path, isolated_env):
    stack_dir = make_stack(
        tmp_path,
        CLEAN_COMPOSE_YAML,
        textwrap.dedent(
            """\
            name: teststack
            description: "test stack"
            repos:
              - github.com/example/teststack
              - github.com/example/mystery-repo
            containers:
              - bozemanpass/web
            pods:
              - name: web
                path: ./web
            """
        ),
    )
    result = validate(stack_dir, isolated_env)
    assert result.returncode == 0
    assert "repos-deprecated" in result.stdout
    # The stack's own repo is derivable and only earns the general deprecation notice;
    # the mystery repo, referenced by nothing, is called out by name.
    assert "mystery-repo" in result.stdout
    assert "repo-unreferenced" in result.stdout
    assert "example/teststack' is not" not in result.stdout


def test_foreign_pod_repository_is_deprecated(tmp_path, isolated_env):
    stack_dir = make_stack(
        tmp_path,
        CLEAN_COMPOSE_YAML,
        textwrap.dedent(
            """\
            name: teststack
            description: "test stack"
            containers:
              - bozemanpass/web
            pods:
              - name: web
                repository: github.com/example/other-repo
                path: ./web
            """
        ),
    )
    result = validate(stack_dir, isolated_env)
    # The pod file resolves under the foreign repo's dev-root path, which does not
    # exist, so the missing pod file is reported as well as the deprecation.
    assert "pod-repository-deprecated" in result.stdout


def test_missing_pod_file_is_an_error(tmp_path, isolated_env):
    stack_dir = make_stack(
        tmp_path,
        CLEAN_COMPOSE_YAML,
        textwrap.dedent(
            """\
            name: teststack
            description: "test stack"
            containers:
              - bozemanpass/web
            pods:
              - name: web
                path: ./web
              - name: ghost
                path: ./ghost
            """
        ),
    )
    result = validate(stack_dir, isolated_env)
    assert result.returncode == 1
    assert "pod-file-missing" in result.stdout
    assert "ghost" in result.stdout


def test_prepare_warns_on_integrity_findings(tmp_path, isolated_env):
    # The advisory hook: prepare reports the same findings as warnings on stderr and
    # still proceeds (fetch-repos stops before any docker use).
    stack_dir = make_stack(
        tmp_path,
        """\
        services:
          web:
            image: bozemanpass/web:stack
          api:
            image: bozemanpass/api:stack
        """,
        textwrap.dedent(CLEAN_STACK_YAML),
    )
    result = run_stack(
        ["prepare", "--stack", str(stack_dir), "--build-policy", "fetch-repos"], isolated_env
    )
    assert result.returncode == 0
    assert "container-undeclared" in result.stderr
