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

"""Tests for digest locking of external images (build/image_pins.py): which images
count as external, the `@stack unpinned` opt-out annotation, and the rewrite of a
deployment's pod file to digest-pinned references.  Digest *resolution* needs a
docker daemon and is exercised by the integration tests instead."""

from conftest import make_stack_from_compose
from stack.build.image_pins import (
    apply_image_locks_to_pod_file,
    external_images_for_stack,
    image_is_unpinned,
    reference_without_tag,
)
from stack.deploy.stack import Stack

DIGEST = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def load_stack(tmp_path, compose_yaml, stack_yaml=None):
    stack_dir = make_stack_from_compose(tmp_path, compose_yaml, stack_yaml=stack_yaml)
    return Stack("teststack").init_from_file(stack_dir / "stack.yml")


def test_reference_without_tag():
    assert reference_without_tag("postgres:14") == "postgres"
    assert reference_without_tag("postgres") == "postgres"
    # A registry host's port is not a tag, and the host is kept.
    assert reference_without_tag("localhost:5000/org/bar:v1") == "localhost:5000/org/bar"
    assert reference_without_tag("localhost:5000/org/bar") == "localhost:5000/org/bar"


def test_external_images_classification(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: bozemanpass/web:stack
          db:
            image: postgres:14
          cache:
            image: redis@{digest}
        """.replace("{digest}", DIGEST),
    )
    # The locally built image has its own identity scheme and the digest-pinned one
    # is already pinned; only postgres:14 is lockable.
    assert external_images_for_stack(stack) == {"postgres:14": False}


def test_unpinned_annotation(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          db:
            image: postgres:14  # @stack unpinned
          cache:
            image: redis:7
        """,
    )
    assert external_images_for_stack(stack) == {"postgres:14": True, "redis:7": False}
    services = stack.load_pod_file("web")["services"]
    assert image_is_unpinned(services["db"])
    assert not image_is_unpinned(services["cache"])


def test_unpinned_annotation_must_be_on_the_image_line(tmp_path):
    # A comment heading the next key attaches to the preceding node in ruamel's
    # model; only the image line's own end-of-line comment counts.
    stack = load_stack(
        tmp_path,
        """\
        services:
          db:
            image: postgres:14
            # @stack unpinned
            restart: always
        """,
    )
    assert external_images_for_stack(stack) == {"postgres:14": False}


def test_apply_image_locks_rewrites_only_locked_externals(tmp_path):
    stack = load_stack(
        tmp_path,
        """\
        services:
          web:
            image: bozemanpass/web:stack
          db:
            image: postgres:14
          opted-out:
            image: mysql:8  # @stack unpinned
          unlocked:
            image: redis:7
        """,
    )
    pod_file = stack.load_pod_file("web")
    apply_image_locks_to_pod_file(pod_file, {"postgres:14": DIGEST, "mysql:8": DIGEST})
    services = pod_file["services"]
    assert services["db"]["image"] == f"postgres@{DIGEST}"
    # Locally built, opted out, and never-locked images are all left alone.
    assert services["web"]["image"] == "bozemanpass/web:stack"
    assert services["opted-out"]["image"] == "mysql:8"
    assert services["unlocked"]["image"] == "redis:7"
