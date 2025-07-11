# Copyright © 2024 Vulcanize

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

from datetime import datetime
from python_on_whales import DockerClient

from stack.log import log_debug
from stack.opts import opts
from stack.util import error_exit


def _publish_tag_for_image(local_image_tag: str, remote_repo: str, version: str):
    # Turns image tags of the form: foo/bar:stack into remote.repo/org/bar:deploy
    (image_name, image_version) = local_image_tag.split(":")
    if image_version == "local" or image_version == "stack":
        return f"{remote_repo}/{image_name}:{version}"
    else:
        error_exit("Asked to publish a non-locally built image")


def publish_image(local_tag, registry, version=None):
    log_debug(f"Publishing this image: {local_tag} to this registry: {registry}")
    docker = DockerClient()
    # Figure out the target image tag
    # Eventually this version will be generated from the source repo state
    # Using a timestemp is an intermediate step
    if not version:
        version = datetime.now().strftime("%Y%m%d%H%M")
    remote_tag = _publish_tag_for_image(local_tag, registry, version)
    # Tag the image thus
    log_debug(f"Tagging {local_tag} to {remote_tag}")
    docker.image.tag(local_tag, remote_tag)
    # Push it to the desired registry
    log_debug(f"Pushing image {remote_tag}")
    docker.image.push(remote_tag)
