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

import click

from stack.build.build_containers import BUILD_POLICIES, build_containers
from stack.config.util import get_config_setting
from stack.deploy.stack import resolve_stack
from stack.repos.repo_util import clone_all_repos_for_stack
from stack.util import error_exit

PREPARE_POLICIES = BUILD_POLICIES[:] + ["fetch-repos"]

@click.command()
@click.option("--stack", help="path to the stack", required=False)
@click.option("--include-containers", help="only build/download these containers")
@click.option("--exclude-containers", help="don't build/download these containers")
@click.option("--include-repos", help="only clone these repositories")
@click.option("--exclude-repos", help="don't clone these repositories")
@click.option("--git-ssh", is_flag=True, default=get_config_setting("git-ssh", False), help="use SSH for git rather than HTTPS")
@click.option("--git-pull", is_flag=True, default=False, help="pull the latest changes for an existing repo")
@click.option("--build-policy", default=PREPARE_POLICIES[0], help=f"Available policies: {PREPARE_POLICIES}")
@click.option("--extra-build-args", help="Supply extra arguments to build")
@click.option("--dont-pull-images", is_flag=True, default=False, help="Don't pull remote images (useful with k8s deployments).")
@click.option("--publish-images", is_flag=True, default=False, help="Publish the built images")
@click.option(
    "--image-registry",
    help="Specify the remote image registry (default: auto-detect per-container)",
    default=get_config_setting("image-registry"),
)
@click.option("--target-arch", help="Specify a target architecture (only for use with --dont-pull-images)")
@click.pass_context
def command(
        ctx,
        stack,
        include_containers,
        exclude_containers,
        include_repos,
        exclude_repos,
        git_ssh,
        git_pull,
        build_policy,
        extra_build_args,
        dont_pull_images,
        publish_images,
        image_registry,
        target_arch,
):
    """build or download stack containers"""

    if build_policy not in PREPARE_POLICIES:
        error_exit(f"{build_policy} is not one of {PREPARE_POLICIES}")

    stack = resolve_stack(stack)
    clone_all_repos_for_stack(stack, include_repos, exclude_repos, git_pull, git_ssh)

    if build_policy == "fetch-repos":
        return

    build_containers(stack, build_policy, image_registry, publish_images, include_containers, exclude_containers,
                     extra_build_args, git_ssh, target_arch, dont_pull_images)
