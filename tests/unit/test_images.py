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

"""Tests for rewriting local image tags into remote-registry tags.

These decide what image a k8s deployment actually pulls, so a wrong answer here shows
up as an ImagePullBackOff with no indication of which rewrite was at fault.
"""

import pytest

from stack.deploy.images import (
    _image_needs_pushed,
    _remote_tag_for_image,
    remote_tag_for_image_unique,
)


REGISTRY = "registry.example.com/org"
DEPLOYMENT_ID = "stack-0123456789abcdef"


@pytest.mark.parametrize(
    "image, expected",
    [
        ("nginx:stack", True),
        ("nginx:local", True),
        ("org/nginx:stack", True),
        ("nginx:latest", False),
        ("nginx:1.27", False),
        # A tag that merely contains the word is not one of the built tags.
        ("nginx:stackdev-abc123", False),
    ],
)
def test_image_needs_pushed(image, expected):
    assert _image_needs_pushed(image) is expected


@pytest.mark.parametrize(
    "image, expected",
    [
        # Locally built tags are redirected at the remote registry...
        ("nginx:stack", f"{REGISTRY}/nginx:deploy"),
        ("nginx:local", f"{REGISTRY}/nginx:deploy"),
        # ...and the org component of a two-part name is dropped, since the remote
        # registry URL already carries its own org.
        ("someorg/nginx:stack", f"{REGISTRY}/nginx:deploy"),
        # Anything else is pulled exactly as named.
        ("nginx:latest", "nginx:latest"),
        ("someorg/nginx:1.27", "someorg/nginx:1.27"),
    ],
)
def test_remote_tag_for_image(image, expected):
    assert _remote_tag_for_image(image, REGISTRY) == expected


@pytest.mark.parametrize(
    "image, expected",
    [
        # The tag is salted with the last 8 characters of the deployment id so that
        # two deployments of the same stack do not collide on one remote tag.
        ("nginx:stack", f"{REGISTRY}/nginx:deploy-89abcdef"),
        ("nginx:local", f"{REGISTRY}/nginx:deploy-89abcdef"),
        ("someorg/nginx:stack", f"{REGISTRY}/nginx:deploy-89abcdef"),
        ("nginx:latest", "nginx:latest"),
        ("someorg/nginx:1.27", "someorg/nginx:1.27"),
    ],
)
def test_remote_tag_for_image_unique(image, expected):
    assert remote_tag_for_image_unique(image, REGISTRY, DEPLOYMENT_ID) == expected


@pytest.mark.parametrize(
    "image, expected",
    [
        # A registry-qualified reference of a released image is pulled as named.
        ("docker.io/library/nginx:1.27", "docker.io/library/nginx:1.27"),
        ("ghcr.io/example/nginx:1.27", "ghcr.io/example/nginx:1.27"),
        # A stack-built image that already lives in a registry is still redirected at
        # this deployment's registry, under its bare name.
        ("ghcr.io/example/nginx:stack", f"{REGISTRY}/nginx:deploy-89abcdef"),
        ("ghcr.io/example/nginx:local", f"{REGISTRY}/nginx:deploy-89abcdef"),
    ],
)
def test_registry_qualified_image_reference(image, expected):
    assert remote_tag_for_image_unique(image, REGISTRY, DEPLOYMENT_ID) == expected


@pytest.mark.parametrize(
    "image, expected",
    [
        # A ':' before the last '/' is a registry port, not a tag.
        ("localhost:5000/nginx:stack", f"{REGISTRY}/nginx:deploy-89abcdef"),
        ("localhost:5000/nginx:1.27", "localhost:5000/nginx:1.27"),
        ("localhost:5000/nginx", "localhost:5000/nginx"),
    ],
)
def test_registry_port_is_not_a_tag(image, expected):
    assert remote_tag_for_image_unique(image, REGISTRY, DEPLOYMENT_ID) == expected


@pytest.mark.parametrize("image", ["nginx", "someorg/nginx", "ghcr.io/example/nginx"])
def test_untagged_image_reference_left_alone(image):
    # Compose treats a missing tag as :latest, which is not a locally built image.
    assert remote_tag_for_image_unique(image, REGISTRY, DEPLOYMENT_ID) == image


def test_digest_pinned_image_reference_left_alone():
    # The ':' here introduces a digest, not a tag, so there is nothing to redirect.
    image = "ghcr.io/example/nginx@sha256:" + "a" * 64
    assert remote_tag_for_image_unique(image, REGISTRY, DEPLOYMENT_ID) == image


@pytest.mark.parametrize(
    "image, expected",
    [
        ("ghcr.io/example/nginx:stack", f"{REGISTRY}/nginx:deploy"),
        ("ghcr.io/example/nginx:1.27", "ghcr.io/example/nginx:1.27"),
        ("localhost:5000/nginx:stack", f"{REGISTRY}/nginx:deploy"),
        ("nginx", "nginx"),
    ],
)
def test_remote_tag_for_image_handles_the_same_reference_forms(image, expected):
    # The non-unique rewriter shared the same parse, so it needs the same coverage.
    assert _remote_tag_for_image(image, REGISTRY) == expected
