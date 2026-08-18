# Copyright © 2023 Vulcanize
# Copyright © 2025 Bozeman Pass, Inc.

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

from typing import Set

from python_on_whales import DockerClient

from stack import constants
from stack.deploy.deployment_context import DeploymentContext
from stack.deploy.deploy_types import DeployCommandContext
from stack.deploy.deploy_util import images_for_deployment
from stack.log import log_debug, log_info
from stack.util import error_exit


# The tags stack builds locally.  Only these are redirected at a deployment's registry;
# any other image is pulled exactly as the pod file names it.
LOCALLY_BUILT_TAGS = ("local", "stack")


def _strip_registry_host(image_name: str):
    """Drop a leading registry host (`ghcr.io/`, `localhost:5000/`) from an image name.

    Follows the standard reference heuristic: the first path component is a host only
    if it contains a '.' or ':' or is exactly "localhost"; otherwise it is an org
    (`someorg/bar` has no host).
    """
    first_component, sep, rest = image_name.partition("/")
    if sep and ("." in first_component or ":" in first_component or first_component == "localhost"):
        return rest
    return image_name


def split_image_reference(image: str):
    """Split an image reference into its host-less name and its tag.

    Any registry host in the reference is dropped, because the remote registry URL
    replacing it carries its own, but the org path is kept -- it is part of the image's
    identity and registries like ghcr require a namespace.  So `org/bar:stack` and
    `foo.io/org/bar:stack` both yield ("org/bar", "stack").

    A ':' only introduces a tag when it follows the last '/' -- a registry host may
    carry a port, as in `localhost:5000/bar`.  The tag is None when there is none,
    which includes digest-pinned references (`bar@sha256:...`, whose "tag" is not a
    tag); neither is a locally built image, so both are left alone by the callers.
    """
    last_path_component = image.rsplit("/", 1)[-1]
    if ":" in last_path_component:
        image_version = last_path_component.rsplit(":", 1)[1]
        image_name = image[: len(image) - len(image_version) - 1]
    else:
        image_name, image_version = image, None
    return _strip_registry_host(image_name), image_version


def _image_needs_pushed(image: str):
    # Only an image stack built locally has to be uploaded; everything else is already
    # wherever it is pulled from.  Shares the tag parse with the rewriters below so that
    # "is this ours" and "rename it" cannot disagree about a reference.
    #
    # A locally built tag that is also published (a prebuilt image prepare pulled, or one
    # a previous --publish-images uploaded) is deployed under that published reference, so
    # it does not need staging either -- see resolve_image_for_deployment.
    if split_image_reference(image)[1] not in LOCALLY_BUILT_TAGS:
        return False
    return _published_reference_for_image(image) is None


def _remote_tag_for_image(image: str, remote_repo_url: str):
    # Turns image tags of the form: org/bar:stack into remote.repo/org/bar:deploy
    image_name, image_version = split_image_reference(image)
    if image_version in LOCALLY_BUILT_TAGS:
        return f"{remote_repo_url}/{image_name}:deploy"
    else:
        return image


# Note: do not add any calls this function
def remote_image_exists(remote_repo_url: str, local_tag: str):
    docker = DockerClient()
    try:
        remote_tag = _remote_tag_for_image(local_tag, remote_repo_url)
        result = docker.manifest.inspect(remote_tag)
        return True if result else False
    except Exception:  # noqa: E722
        return False


# Note: do not add any calls this function
def add_tags_to_image(remote_repo_url: str, local_tag: str, *additional_tags):
    if not additional_tags:
        return

    if not remote_image_exists(remote_repo_url, local_tag):
        raise Exception(f"{local_tag} does not exist in {remote_repo_url}")

    docker = DockerClient()
    remote_tag = _remote_tag_for_image(local_tag, remote_repo_url)
    new_remote_tags = [_remote_tag_for_image(tag, remote_repo_url) for tag in additional_tags]
    docker.buildx.imagetools.create(sources=[remote_tag], tags=new_remote_tags)


def remote_tag_for_image_unique(image: str, remote_repo_url: str, deployment_id: str):
    # Turns image tags of the form: org/bar:stack into remote.repo/org/bar:deploy-<id>
    image_name, image_version = split_image_reference(image)
    if image_version in LOCALLY_BUILT_TAGS:
        # Salt the tag with part of the deployment id to make it unique to this deployment
        deployment_tag = deployment_id[-8:]
        return f"{remote_repo_url}/{image_name}:deploy-{deployment_tag}"
    else:
        return image


def is_staged_reference(image: str, deployment_id: str):
    """True when the reference is this deployment's private mutable staging tag.

    Such a reference is the one case where new image content arrives under an
    unchanged name, so picking it up means forcing a re-pull rather than a spec
    change -- see K8sDeployer.update.
    """
    return image.endswith(f":deploy-{deployment_id[-8:]}")


def stale_staged_images(images, image_registry: str, deployment_id: str):
    """Staged images whose current local build has not been pushed.

    For each image the deployment pulls from the staging registry, compare the
    local source build (`org/bar:stack`) against the local record of what
    push-images last staged: push tags the staged reference locally, so the two
    disagreeing means a rebuild has not been uploaded.  An image with no local
    source build is skipped -- on a machine that never built it there is nothing
    to judge staleness against.

    Returns a list of (source_image, staged_reference) pairs.
    """
    stale = []
    if not image_registry:
        return stale
    docker = DockerClient()

    def local_id(tag):
        try:
            return docker.image.inspect(tag).id
        except Exception:
            return None

    for image in sorted(images):
        _, image_version = split_image_reference(image)
        if image_version not in LOCALLY_BUILT_TAGS or _published_reference_for_image(image):
            continue
        source_id = local_id(image)
        if source_id is None:
            continue
        staged_reference = remote_tag_for_image_unique(image, image_registry, deployment_id)
        if local_id(staged_reference) != source_id:
            stale.append((image, staged_reference))
    return stale


def _published_reference_for_image(image: str):
    """Find the registry-qualified reference under which a locally built image is published.

    `stack prepare` leaves the answer in the local daemon's tags: pulling a prebuilt
    image records `ghcr.io/org/bar:<hash>` alongside the `org/bar:<hash>` and
    `org/bar:stack` cross-tags, and `--publish-images` tags what it pushes the same
    way.  So a sibling tag that carries a registry host, and whose name and version
    match an unqualified sibling, is a reference the cluster can pull directly.

    Requiring the version to also exist as an unqualified tag keeps deployment-private
    staging tags (`reg/org/bar:deploy-xxxx`, which have no unqualified counterpart)
    from being mistaken for a published image.

    Returns None when the image has no such tag -- or does not exist locally at all.
    """
    image_name, _ = split_image_reference(image)
    try:
        repo_tags = DockerClient().image.inspect(image).repo_tags
    except Exception:
        return None

    local_versions = set()
    qualified = []
    for ref in repo_tags:
        ref_name, ref_version = split_image_reference(ref)
        if not ref_version or ref_version in LOCALLY_BUILT_TAGS or ref_name != image_name:
            continue
        if ref_version.startswith("stackdev-"):
            # A stackdev version identifies a local development build; it is never published.
            continue
        if _strip_registry_host(ref) == ref:
            local_versions.add(ref_version)
        else:
            qualified.append((ref_version, ref))
    matches = sorted(ref for ref_version, ref in qualified if ref_version in local_versions)
    return matches[0] if matches else None


def resolve_image_for_deployment(image: str, image_registry: str, deployment_id: str) -> str:
    """Return the image reference a (non-kind) k8s pod spec should use.

    Images not tagged as locally built are pulled exactly as the pod file names them.

    A locally built image that is already published -- a prebuilt image `prepare` pulled,
    or one `--publish-images` uploaded -- is pulled under that published reference.  Its
    tag is the content-addressed recipe hash, so it already isolates deployments from each
    other the way a staging tag does, and staging it again would push a byte-identical copy
    under a second name.  Only an image with no published reference is redirected at the
    deployment's staging registry, matching what push-images uploads.

    If neither exists the deployment cannot work, so fail now with the remedy rather than
    as an ImagePullBackOff later.
    """
    _, image_version = split_image_reference(image)
    if image_version not in LOCALLY_BUILT_TAGS:
        return image
    published = _published_reference_for_image(image)
    if published:
        log_debug(f"Using published image {published} for {image}")
        return published
    if image_registry:
        return remote_tag_for_image_unique(image, image_registry, deployment_id)
    error_exit(
        f"Cannot resolve image {image} for deployment: it is not published to a registry and"
        f" the spec has no image-registry to stage it through.  Either publish it"
        f" (stack prepare --publish-images --image-registry <url>), or add an image registry"
        f" to the deployment (stack init --image-registry <url> ...) and upload the image with"
        f" 'stack manage --dir <deployment-dir> push-images'.  If the stack has not been"
        f" prepared on this machine, run 'stack prepare' first."
    )


# TODO: needs lots of error handling
def push_images_operation(command_context: DeployCommandContext, deployment_context: DeploymentContext):
    # Get the list of images for the stack
    cluster_context = command_context.cluster_context
    images: Set[str] = images_for_deployment(cluster_context.compose_files)
    # Only images the deployment will actually pull from the staging registry are uploaded.
    # This is the same test resolve_image_for_deployment applies, so the two cannot disagree
    # about which images are staged and which are pulled from where they are published.
    images_to_push = sorted(image for image in images if _image_needs_pushed(image))
    if not images_to_push:
        log_info("No images need pushing: every image is already published or is pulled as named.")
        return
    # Tag the images for the remote repo
    remote_repo_url = deployment_context.spec.obj.get(constants.image_registry_key)
    if not remote_repo_url:
        error_exit(
            "The spec has no image-registry to push to."
            "  Re-run 'stack init' with --image-registry <url> to configure one."
        )
    docker = DockerClient()
    for image in images_to_push:
        remote_tag = remote_tag_for_image_unique(image, remote_repo_url, deployment_context.id)
        log_debug(f"Tagging {image} to {remote_tag}")
        docker.image.tag(image, remote_tag)
    # Run docker push commands to upload
    for image in images_to_push:
        remote_tag = remote_tag_for_image_unique(image, remote_repo_url, deployment_context.id)
        log_debug(f"Pushing image {remote_tag}")
        docker.image.push(remote_tag)
