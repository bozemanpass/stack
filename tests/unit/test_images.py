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

"""Tests for resolving local image tags into the references a deployment pulls.

These decide what image a k8s deployment actually pulls, so a wrong answer here shows
up as an ImagePullBackOff with no indication of which rewrite was at fault.
"""

import pytest

from stack.deploy.images import (
    _image_needs_pushed,
    _published_reference_for_image,
    _remote_tag_for_image,
    _strip_registry_host,
    remote_tag_for_image_unique,
    resolve_image_for_deployment,
)


REGISTRY = "registry.example.com/org"
DEPLOYMENT_ID = "stack-0123456789abcdef"
HASH = "0123456789abcdef0123456789abcdef01234567"


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
    "name, expected",
    [
        # A first component with a '.', a ':' or exactly "localhost" is a registry host.
        ("ghcr.io/someorg/nginx", "someorg/nginx"),
        ("localhost:5000/nginx", "nginx"),
        ("localhost/nginx", "nginx"),
        # Anything else is an org, which is part of the image's identity.
        ("someorg/nginx", "someorg/nginx"),
        ("nginx", "nginx"),
    ],
)
def test_strip_registry_host(name, expected):
    assert _strip_registry_host(name) == expected


@pytest.mark.parametrize(
    "image, expected",
    [
        # Locally built tags are redirected at the remote registry...
        ("nginx:stack", f"{REGISTRY}/nginx:deploy"),
        ("nginx:local", f"{REGISTRY}/nginx:deploy"),
        # ...keeping the org component, which is part of the image's identity (and
        # required by registries like ghcr), but not any host, since the remote
        # registry URL carries its own.
        ("someorg/nginx:stack", f"{REGISTRY}/someorg/nginx:deploy"),
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
        ("someorg/nginx:stack", f"{REGISTRY}/someorg/nginx:deploy-89abcdef"),
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
        # this deployment's registry: the host is replaced, the org kept.
        ("ghcr.io/example/nginx:stack", f"{REGISTRY}/example/nginx:deploy-89abcdef"),
        ("ghcr.io/example/nginx:local", f"{REGISTRY}/example/nginx:deploy-89abcdef"),
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
        ("ghcr.io/example/nginx:stack", f"{REGISTRY}/example/nginx:deploy"),
        ("ghcr.io/example/nginx:1.27", "ghcr.io/example/nginx:1.27"),
        ("localhost:5000/nginx:stack", f"{REGISTRY}/nginx:deploy"),
        ("nginx", "nginx"),
    ],
)
def test_remote_tag_for_image_handles_the_same_reference_forms(image, expected):
    # The non-unique rewriter shares the same parse, so it needs the same coverage.
    assert _remote_tag_for_image(image, REGISTRY) == expected


class _FakeImage:
    def __init__(self, repo_tags):
        self.repo_tags = repo_tags


class _FakeDockerClient:
    """Stands in for DockerClient in images.py; serves one image's repo_tags."""

    _repo_tags = None

    def __init__(self):
        self.image = self

    def inspect(self, image):
        if self._repo_tags is None:
            raise Exception(f"No such image: {image}")
        return _FakeImage(self._repo_tags)


@pytest.fixture
def local_repo_tags(monkeypatch):
    def _set(repo_tags):
        _FakeDockerClient._repo_tags = repo_tags
        monkeypatch.setattr("stack.deploy.images.DockerClient", _FakeDockerClient)

    yield _set
    _FakeDockerClient._repo_tags = None


def test_published_reference_found_from_prepare_cross_tags(local_repo_tags):
    # The tag set stack prepare leaves behind after pulling a prebuilt image.
    local_repo_tags(
        [
            f"exampleorg/myapp:{HASH}",
            "exampleorg/myapp:stack",
            "exampleorg/myapp:local",
            f"ghcr.io/exampleorg/myapp:{HASH}",
        ]
    )
    assert _published_reference_for_image("exampleorg/myapp:stack") == f"ghcr.io/exampleorg/myapp:{HASH}"


def test_published_reference_ignores_staging_deploy_tags(local_repo_tags):
    # A deployment-private staging tag has no unqualified counterpart, so it must not
    # be mistaken for a published image.
    local_repo_tags(
        [
            f"exampleorg/myapp:{HASH}",
            "exampleorg/myapp:stack",
            "registry.example.com/exampleorg/myapp:deploy-89abcdef",
        ]
    )
    assert _published_reference_for_image("exampleorg/myapp:stack") is None


def test_published_reference_ignores_stackdev_versions(local_repo_tags):
    # A stackdev version identifies a local development build; it is never published.
    local_repo_tags(
        [
            "exampleorg/myapp:stackdev-abc123",
            "exampleorg/myapp:stack",
            "ghcr.io/exampleorg/myapp:stackdev-abc123",
        ]
    )
    assert _published_reference_for_image("exampleorg/myapp:stack") is None


def test_published_reference_ignores_other_images_tags(local_repo_tags):
    # A qualified tag for a different image name proves nothing about this one.
    local_repo_tags(
        [
            "exampleorg/myapp:stack",
            f"exampleorg/myapp:{HASH}",
            f"ghcr.io/otherorg/otherapp:{HASH}",
        ]
    )
    assert _published_reference_for_image("exampleorg/myapp:stack") is None


def test_published_reference_none_when_image_absent(local_repo_tags):
    local_repo_tags(None)  # inspect raises, as when the image was never prepared
    assert _published_reference_for_image("exampleorg/myapp:stack") is None


def test_resolve_prefers_staging_registry_when_configured(local_repo_tags):
    # With a staging registry in the spec, the deployment pulls what push-images
    # uploads, even if the image is also published somewhere.
    local_repo_tags(["exampleorg/myapp:stack", f"ghcr.io/exampleorg/myapp:{HASH}", f"exampleorg/myapp:{HASH}"])
    assert (
        resolve_image_for_deployment("exampleorg/myapp:stack", REGISTRY, DEPLOYMENT_ID)
        == f"{REGISTRY}/exampleorg/myapp:deploy-89abcdef"
    )


def test_resolve_uses_published_reference_without_staging_registry(local_repo_tags):
    local_repo_tags(["exampleorg/myapp:stack", f"ghcr.io/exampleorg/myapp:{HASH}", f"exampleorg/myapp:{HASH}"])
    assert (
        resolve_image_for_deployment("exampleorg/myapp:stack", None, DEPLOYMENT_ID)
        == f"ghcr.io/exampleorg/myapp:{HASH}"
    )


def test_resolve_leaves_upstream_images_alone(local_repo_tags):
    local_repo_tags(None)
    assert resolve_image_for_deployment("postgres:16", None, DEPLOYMENT_ID) == "postgres:16"


def test_resolve_fails_fast_when_image_is_unreachable(local_repo_tags):
    # Locally built, not published, and no staging registry: the deployment cannot
    # work, so this must error at create time, not ImagePullBackOff later.
    local_repo_tags(["exampleorg/myapp:stack", "exampleorg/myapp:stackdev-abc123"])
    with pytest.raises(SystemExit):
        resolve_image_for_deployment("exampleorg/myapp:stack", None, DEPLOYMENT_ID)
