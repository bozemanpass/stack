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


@pytest.mark.xfail(
    strict=True,
    reason="A registry-qualified image reference raises ValueError.  Both functions do "
    "image.split('/', 2) and then assume element [1] carries the ':tag'.  That holds "
    "for 'org/img:tag' but for 'host/org/img:tag' element [1] is the org, which has "
    "no ':' -- so the unpack fails.  Any k8s deployment with image-registry set and a "
    "registry-qualified image in a pod file hits this, including stack-built images "
    "that already live in a registry (ghcr.io/org/img:stack).",
)
@pytest.mark.parametrize(
    "image",
    [
        "docker.io/library/nginx:1.27",
        "ghcr.io/example/nginx:1.27",
        "ghcr.io/example/nginx:stack",
    ],
)
def test_registry_qualified_image_reference(image):
    # Both rewriters share the flaw; asserting on the unique one is enough to pin it.
    assert remote_tag_for_image_unique(image, REGISTRY, DEPLOYMENT_ID)


def test_untagged_image_reference():
    # An image with no tag at all also fails to unpack.  Compose treats a missing tag
    # as :latest, which would mean "leave it alone".
    with pytest.raises(ValueError):
        remote_tag_for_image_unique("nginx", REGISTRY, DEPLOYMENT_ID)
