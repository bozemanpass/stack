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

"""Digest locking for external images.

A stack's locally built images are already version-locked: their tag is the recipe
repo's commit hash (see build_util.ImageIdentity).  An *external* image -- anything a
pod file names with a tag outside LOCALLY_BUILT_TAGS, `postgres:14` say -- had no part
in that story: `postgres:14` is a mutable reference, so two deployments of the same
stack commit could run different bytes.

This module closes that gap without a second declaration site.  The pod file remains
the one authoritative statement of which external image is used; `stack prepare`
resolves each one to its content digest and records it in the `images` section of the
stack.lock beside the stack.yml, and `stack deploy` rewrites the deployment's copy of
the pod file to the digest-pinned form (`postgres@sha256:...`).  Committing the lock
file is what stabilizes the choice, exactly as with the other lock sections.

A pod file opts one image out with an end-of-line annotation:

    image: postgres:14  # @stack unpinned

An existing pin is never silently re-resolved: moving to a newer upstream image means
deleting the entry (or the lock file) and running `stack prepare` again.
"""

from python_on_whales import DockerClient

from stack import constants
from stack.build.build_util import read_stack_locks, write_stack_locks
from stack.deploy.images import LOCALLY_BUILT_TAGS, split_image_reference
from stack.deploy.stack import Stack, get_parsed_stack_config
from stack.log import log_debug, log_info, log_warn


def reference_without_tag(image: str):
    """The reference as written, minus any tag: registry host and org path are kept,
    because the pin must name the same repository the pod file pulled from."""
    last_path_component = image.rsplit("/", 1)[-1]
    if ":" in last_path_component:
        tag = last_path_component.rsplit(":", 1)[1]
        return image[: len(image) - len(tag) - 1]
    return image


def image_is_unpinned(service_node):
    """True when the service's image: line carries the `@stack unpinned` annotation.

    Only the first line of each comment token counts: ruamel attaches trailing
    full-line comments (e.g. one heading the next key) to the preceding item, the
    same trap the other annotation parsers guard against."""
    ca = getattr(service_node, "ca", None)
    if ca is None:
        return False

    first_lines = []

    def walk(entry):
        if entry is None:
            return
        if isinstance(entry, list):
            for item in entry:
                walk(item)
        else:
            first_lines.append(entry.value.split("\n", 1)[0])

    walk(ca.items.get("image"))
    for line in first_lines:
        if constants.stack_annotation_marker in line and constants.unpinned_annotation in line.split():
            return True
    return False


def _lockable_image(image: str):
    """Whether this reference participates in digest locking at all.

    Locally built tags have their own identity scheme; a reference that already
    carries a digest is pinned in place; and an interpolated one is rejected by
    validation rather than guessed at here."""
    if not image or "$" in image or "@" in image:
        return False
    return split_image_reference(image)[1] not in LOCALLY_BUILT_TAGS


def external_images_for_stack(stack: Stack):
    """{image reference as written: unpinned?} over the stack's pod files.

    An image annotated unpinned anywhere is unpinned everywhere: one pod's copy
    being rewritten while another's is not would deploy two different images under
    what the stack author wrote as one."""
    result = {}
    for pod_name in stack.get_pod_list():
        parsed_pod_file = stack.load_pod_file(pod_name)
        services = (parsed_pod_file or {}).get(constants.services_key) or {}
        for svc in services.values():
            image = svc.get("image") if isinstance(svc, dict) else None
            if image and _lockable_image(str(image)):
                image = str(image)
                result[image] = result.get(image, False) or image_is_unpinned(svc)
    return result


def resolve_image_digest(image: str, allow_pull=True):
    """The manifest digest the reference currently resolves to, or None.

    Read from the local daemon's RepoDigests record, pulling first if needed: the
    digest recorded at pull is the registry's manifest digest, so it is the value a
    `name@digest` reference must carry to pull the same content anywhere."""
    docker = DockerClient()

    def inspect():
        try:
            return docker.image.inspect(image)
        except Exception:
            return None

    info = inspect()
    if info is None and allow_pull:
        log_info(f"Pulling {image} to determine its digest")
        try:
            docker.image.pull(image, quiet=True)
        except Exception as e:
            log_warn(f"WARN: could not pull {image}: {e}")
            return None
        info = inspect()
    if info is None:
        return None

    repo = reference_without_tag(image)
    digests = info.repo_digests or []
    for repo_digest in digests:
        digest_repo, _, digest = str(repo_digest).partition("@")
        if digest_repo == repo:
            return digest
    if len(digests) == 1:
        # The daemon may qualify the repository (docker.io/library/postgres) where the
        # pod file does not; with only one recorded digest there is nothing to confuse.
        return str(digests[0]).partition("@")[2]
    log_debug(f"No repo digest for {image} matches {repo}: {digests}")
    return None


def lock_external_images(parent_stack: Stack, allow_pull=True):
    """Resolve and record a digest for each unlocked external image, per stack.

    Follows a super stack into its required stacks; each stack's pins are written to
    its own stack.lock, beside the stack.yml whose pod files name the images."""
    for stack_path in parent_stack.get_required_stacks_paths():
        stack = get_parsed_stack_config(stack_path)
        if not stack.file_path:
            continue
        stack_dir = stack.file_path.parent
        locks = read_stack_locks(stack_dir)
        changed = False
        for image, unpinned in sorted(external_images_for_stack(stack).items()):
            if unpinned:
                if image in locks["images"]:
                    log_info(f"Unlocking {image}: it is annotated {constants.unpinned_annotation}")
                    del locks["images"][image]
                    changed = True
                continue
            if image in locks["images"]:
                log_debug(f"{image} already locked to {locks['images'][image]}")
                continue
            digest = resolve_image_digest(image, allow_pull=allow_pull)
            if digest:
                log_info(f"Locking {image} to {digest}")
                locks["images"][image] = digest
                changed = True
            else:
                log_warn(f"WARN: could not resolve a digest for {image}; it remains unlocked")
        if changed:
            write_stack_locks(stack_dir, locks)


def apply_image_locks_to_pod_file(parsed_pod_file, image_locks: dict):
    """Rewrite a deployment's copy of a pod file to the digest-pinned references.

    The source pod file keeps the readable tag; only the deployment artifact is
    pinned, the same division of labor as the compose :stack tag rewrite."""
    services = (parsed_pod_file or {}).get(constants.services_key) or {}
    for svc in services.values():
        image = svc.get("image") if isinstance(svc, dict) else None
        if not image or not _lockable_image(str(image)) or image_is_unpinned(svc):
            continue
        digest = image_locks.get(str(image))
        if digest:
            svc["image"] = f"{reference_without_tag(str(image))}@{digest}"
