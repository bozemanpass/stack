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
import git
import os
import sys

from stack import constants
from stack.build.build_util import (
    get_containers_in_scope,
    container_exists_locally,
    container_exists_remotely,
    local_container_arch,
    ContainerSpec,
)
from stack.config.util import get_config_setting
from stack.config.util import get_dev_root_path
from stack.deploy.stack import resolve_stack, get_parsed_stack_config
from stack.log import log_debug, output_main
from stack.opts import opts
from stack.repos.repo_util import (
    fs_path_for_repo,
    image_registry_for_repo,
    get_repo_current_hash,
    is_repo_dirty,
    get_container_tag_for_repo,
    host_and_path_for_repo,
)
from stack.util import get_yaml


def container_disposition(parent_stack, image_registry, git_ssh):
    ret = {}
    required_stacks = parent_stack.get_required_stacks_paths()

    for stack_path in required_stacks:
        if not stack_path.exists():
            shorter_path = stack_path.relative_to(get_dev_root_path())
            log_debug(f"Missing stack {shorter_path} required by {parent_stack.name}.")
            ret[str(shorter_path)] = "missing"
            continue

        stack = get_parsed_stack_config(stack_path)
        containers_in_scope = get_containers_in_scope(stack)

        for stack_container in containers_in_scope:
            if (not stack_container.ref or stack_container.ref == ".") and stack.get_repo_ref():
                stack_container.ref = stack.get_repo_ref()

            container_repo_fs_path = fs_path_for_repo(stack_container.ref, get_dev_root_path())
            if not os.path.exists(container_repo_fs_path):
                log_debug(f"Missing ref {stack_container.ref} needed by {stack_container.name}.")
                ret[stack_container.ref] = "missing"
                continue

            container_spec_yml_path = os.path.join(container_repo_fs_path, constants.container_file_name)
            container_lock_file_path = os.path.join(container_repo_fs_path, constants.container_lock_file_name)
            if stack_container.path:
                container_spec_yml_path = os.path.join(container_repo_fs_path, stack_container.path, constants.container_file_name)
                container_lock_file_path = os.path.join(
                    container_repo_fs_path, stack_container.path, constants.container_lock_file_name
                )

            tag = "stack"
            if os.path.exists(container_lock_file_path):
                tag = get_yaml().load(open(container_lock_file_path, "r")).get("hash")
                log_debug(f"{stack_container.name}: Read locked hash {tag} from {container_lock_file_path}")
            else:
                local_repo_path_to_check = container_repo_fs_path
                if os.path.exists(container_spec_yml_path):
                    container_spec = ContainerSpec().init_from_file(container_spec_yml_path)
                    if container_spec.ref and container_spec.ref != ".":
                        ref_fs_path = fs_path_for_repo(container_spec.ref, get_dev_root_path())
                        if not os.path.exists(ref_fs_path):
                            local_repo_path_to_check = None
                            repo_host, repo_path, branch_or_hash_from_spec = host_and_path_for_repo(container_spec.ref)
                            log_debug("Branch or hash from spec is: " + str(branch_or_hash_from_spec))
                            repo = f"https://{repo_host}/{repo_path}"
                            if git_ssh:
                                repo = f"git@{repo_host}:{repo_path}"
                            git_client = git.cmd.Git()
                            result = git_client.ls_remote(repo, branch_or_hash_from_spec)
                            if result:
                                tag = result.split()[0]
                                log_debug(f"{stack_container.name}: Using remote hash {tag} from {repo}.")
                        else:
                            local_repo_path_to_check = ref_fs_path

                if local_repo_path_to_check:
                    if is_repo_dirty(local_repo_path_to_check):
                        tag = get_container_tag_for_repo(local_repo_path_to_check)
                        log_debug(
                            f"{stack_container.name}: No lock file, repo {local_repo_path_to_check} has local modifications {tag}."
                        )
                    else:
                        git_hash = get_repo_current_hash(local_repo_path_to_check)
                        if git_hash:
                            tag = git_hash
                            log_debug(
                                f"{stack_container.name}: No lock file, using git HEAD hash {tag} from {local_repo_path_to_check}."
                            )
                        else:
                            log_debug(f"{stack_container.name}: No lock file, using 'stack' as image tag.")

            container_tag = f"{stack_container.name}:{tag}"
            exists_locally = container_exists_locally(container_tag)
            if exists_locally:
                log_debug(f"{container_tag} exists locally: {exists_locally}")
                ret[container_tag] = "local"
            else:
                image_registries_to_check = [r for r in [image_registry, image_registry_for_repo(stack_container.ref)] if r]
                exists_remotely, image_registry_to_pull_this_container = container_exists_remotely(
                    container_tag, image_registries_to_check, local_container_arch()
                )
                if exists_remotely:
                    log_debug(f"{container_tag} exists remotely: {exists_remotely}")
                    ret[container_tag] = "remote:" + image_registry_to_pull_this_container
                else:
                    ret[container_tag] = "needs-built"

    return ret


@click.command()
@click.option("--stack", help="name or path of the stack", required=False)
@click.option(
    "--image-registry",
    help="Provide a container image registry url for this k8s cluster",
    default=get_config_setting("image-registry"),
)
@click.option(
    "--git-ssh/--no-git-ssh", is_flag=True, default=get_config_setting("git-ssh", False), help="use SSH for git rather than HTTPS"
)
@click.pass_context
def command(ctx, stack, image_registry, git_ssh):
    """check if stack containers are ready"""

    stack = resolve_stack(stack)
    what_needs_done = container_disposition(stack, image_registry, git_ssh)

    padding = 8
    max_name_len = 0
    for name in what_needs_done.keys():
        max_name_len = max(max_name_len, len(name))

    all_ready = True
    for name, status in what_needs_done.items():
        if status == "local":
            status_msg = "ready"
        elif status.startswith("remote:"):
            status_msg = "available from " + status[7:]
            all_ready = False
        elif status == "missing":
            status_msg = "repo needs fetched"
            all_ready = False
        else:
            status_msg = "needs built"
            all_ready = False
        output_main(f"{name.ljust(max_name_len + padding)} {status_msg}")

    if all_ready:
        if not opts.o.quiet:
            output_main("\nAll containers are ready to use.", console=sys.stderr)
        sys.exit(0)
    else:
        if not opts.o.quiet:
            output_main(f"\nRun 'stack prepare --stack {stack.name}' to prepare missing containers.", console=sys.stderr)
        sys.exit(1)
