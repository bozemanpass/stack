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
from stack.log import log_debug


# The tags stack builds locally.  Only these are redirected at a deployment's registry;
# any other image is pulled exactly as the pod file names it.
LOCALLY_BUILT_TAGS = ("local", "stack")


def _split_image_reference(image: str):
    """Split an image reference into its bare name and its tag.

    The name is the last path component: any host and org in the reference are dropped,
    because the remote registry URL replacing them carries its own.  So both
    `bar:stack` and `foo.io/org/bar:stack` yield ("bar", "stack").

    A ':' only introduces a tag when it follows the last '/' -- a registry host may
    carry a port, as in `localhost:5000/bar`.  The tag is None when there is none,
    which includes digest-pinned references (`bar@sha256:...`, whose "tag" is not a
    tag); neither is a locally built image, so both are left alone by the callers.
    """
    last_path_component = image.rsplit("/", 1)[-1]
    if ":" in last_path_component:
        image_name, image_version = last_path_component.rsplit(":", 1)
    else:
        image_name, image_version = last_path_component, None
    return image_name, image_version


def _image_needs_pushed(image: str):
    # Only an image stack built locally has to be uploaded; everything else is already
    # wherever it is pulled from.  Shares the tag parse with the rewriters below so that
    # "is this ours" and "rename it" cannot disagree about a reference.
    return _split_image_reference(image)[1] in LOCALLY_BUILT_TAGS


def _remote_tag_for_image(image: str, remote_repo_url: str):
    # Turns image tags of the form: foo/bar:stack into remote.repo/org/bar:deploy
    image_name, image_version = _split_image_reference(image)
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
    # Turns image tags of the form: foo/bar:stack into remote.repo/org/bar:deploy
    image_name, image_version = _split_image_reference(image)
    if image_version in LOCALLY_BUILT_TAGS:
        # Salt the tag with part of the deployment id to make it unique to this deployment
        deployment_tag = deployment_id[-8:]
        return f"{remote_repo_url}/{image_name}:deploy-{deployment_tag}"
    else:
        return image


# TODO: needs lots of error handling
def push_images_operation(command_context: DeployCommandContext, deployment_context: DeploymentContext):
    # Get the list of images for the stack
    cluster_context = command_context.cluster_context
    images: Set[str] = images_for_deployment(cluster_context.compose_files)
    # Tag the images for the remote repo
    remote_repo_url = deployment_context.spec.obj[constants.image_registry_key]
    docker = DockerClient()
    for image in images:
        if _image_needs_pushed(image):
            remote_tag = remote_tag_for_image_unique(image, remote_repo_url, deployment_context.id)
            log_debug(f"Tagging {image} to {remote_tag}")
            docker.image.tag(image, remote_tag)
    # Run docker push commands to upload
    for image in images:
        if _image_needs_pushed(image):
            remote_tag = remote_tag_for_image_unique(image, remote_repo_url, deployment_context.id)
            log_debug(f"Pushing image {remote_tag}")
            docker.image.push(remote_tag)
