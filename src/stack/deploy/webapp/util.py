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

import hashlib
import json
import os
import random
import sys
import tempfile

from stack.util import run_shell_command, error_exit
from stack.log import log_error, log_info


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self

    def __getattribute__(self, attr):
        __dict__ = super(AttrDict, self).__getattribute__("__dict__")
        if attr in __dict__:
            v = super(AttrDict, self).__getattribute__(attr)
            if isinstance(v, dict):
                return AttrDict(v)
            return v


def file_hash(filename):
    return hashlib.sha1(open(filename).read().encode()).hexdigest()


def determine_base_container(clone_dir, app_type="webapp"):
    if not app_type or not app_type.startswith("webapp"):
        raise Exception(f"Unsupported app_type {app_type}")

    base_container = "bozemanpass/webapp-base"
    if app_type == "webapp/next":
        base_container = "bozemanpass/nextjs-base"
    elif app_type == "webapp":
        pkg_json_path = os.path.join(clone_dir, "package.json")
        if os.path.exists(pkg_json_path):
            pkg_json = json.load(open(pkg_json_path))
            if "next" in pkg_json.get("dependencies", {}):
                base_container = "bozemanpass/nextjs-base"

    return base_container


def build_container_image(app_record, tag, extra_build_args=None):
    if extra_build_args is None:
        extra_build_args = []
    tmpdir = tempfile.mkdtemp()

    # TODO: determine if this code could be calling into the Python git library like fetch repositories
    try:
        record_id = app_record["id"]
        ref = app_record.attributes.repository_ref
        repo = random.choice(app_record.attributes.repository)
        clone_dir = os.path.join(tmpdir, record_id)

        log_info(f"Cloning repository {repo} to {clone_dir} ...")
        # Set github credentials if present running a command like:
        # git config --global url."https://${TOKEN}:@github.com/".insteadOf "https://github.com/"
        github_token = os.environ.get("DEPLOYER_GITHUB_TOKEN")
        if github_token:
            log_info("Github token detected, setting it in the git environment")
            git_config_args = [
                "git",
                "config",
                "--global",
                f"url.https://{github_token}:@github.com/.insteadOf",
                "https://github.com/",
            ]
            run_shell_command(git_config_args)
        if ref:
            # TODO: Determing branch or hash, and use depth 1 if we can.
            git_env = dict(os.environ.copy())
            # Never prompt
            git_env["GIT_TERMINAL_PROMPT"] = "0"
            try:
                run_shell_command(f"git clone {repo} {clone_dir}", env=git_env)
            except Exception as e:
                log_error(f"git clone failed.  Is the repository {repo} private?")
                raise e

            try:
                run_shell_command(f"git checkout {ref}", cwd=clone_dir, env=git_env)
            except Exception as e:
                log_error(f"git checkout failed.  Does ref {ref} exist?")
                raise e
        else:
            # TODO: why is this code different vs the branch above (run vs check_call, and no prompt disable)?
            run_shell_command(f"git checkout {ref}", cwd=clone_dir, env=git_env)
            run_shell_command(f"git clone --depth 1 {repo} {clone_dir}")

        base_container = determine_base_container(clone_dir, app_record.attributes.app_type)

        log_info("Building webapp ...")
        build_command = [
            sys.argv[0],
            "--verbose",
            "webapp build",
            "--source-repo",
            clone_dir,
            "--tag",
            tag,
            "--base-container",
            base_container,
        ]
        if extra_build_args:
            build_command.append("--extra-build-args")
            build_command.append(" ".join(extra_build_args))

        rc = run_shell_command(build_command)
        if rc != 0:
            error_exit(f"{build_command} failed")
    finally:
        run_shell_command(f"rm -rf '{tmpdir}'")


def push_container_image(deployment_dir, logger):
    log_info("Pushing images ...")
    run_shell_command(f"'{sys.argv[0]}' manage --dir '{deployment_dir}' push-images")
    log_info("Finished pushing images.")


def deploy_to_k8s(deploy_record, deployment_dir, recreate, logger):
    log_info("Deploying to k8s ...")

    if recreate:
        commands_to_run = ["stop", "start"]
    else:
        if not deploy_record:
            commands_to_run = ["start"]
        else:
            commands_to_run = ["update"]

    for command in commands_to_run:
        log_info(f"Running {command} command on deployment dir: {deployment_dir}")
        run_shell_command(f"'{sys.argv[0]}' manage --dir '{deployment_dir}' {command}")
        log_info(f"Finished {command} command on deployment dir: {deployment_dir}")

    log_info("Finished deploying to k8s.")


def skip_by_tag(r, include_tags, exclude_tags):
    for tag in exclude_tags:
        if r.attributes.tags and tag in r.attributes.tags:
            return True

    if include_tags:
        for tag in include_tags:
            if r.attributes.tags and tag in r.attributes.tags:
                return False
        return True

    return False
