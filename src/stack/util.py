# Copyright © 2022, 2023 Vulcanize
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

import os.path
import asyncio
import sys
import ruamel.yaml

from pathlib import Path
from dotenv import dotenv_values
from typing import Mapping

from stack.constants import deployment_file_name, compose_file_prefix
from stack.log import log_error, log_warn, output_subcmd, log_debug

STACK_USE_BUILTIN_STACK = "true" == os.environ.get("STACK_USE_BUILTIN_STACK", "false")


async def _read_stream(stream, cb):
    while True:
        line = await stream.readline()
        if line:
            cb(line)
        else:
            break


async def _stream_subprocess(cmd, env, cwd, stdout_cb, stderr_cb):
    process = await asyncio.create_subprocess_shell(
        cmd, env=env, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    await asyncio.gather(
        _read_stream(process.stdout, lambda lout: stdout_cb(lout.decode().rstrip())),
        _read_stream(process.stderr, lambda lerr: stderr_cb(lerr.decode().rstrip())),
    )

    return await process.wait()


def _sub_execute(cmd, env=os.environ, cwd=None, stdout_cb=output_subcmd, stderr_cb=output_subcmd):
    rc = 1
    loop = asyncio.new_event_loop()
    try:
        rc = loop.run_until_complete(
            _stream_subprocess(
                cmd,
                env,
                cwd,
                stdout_cb,
                stderr_cb,
            )
        )
    finally:
        loop.close()
    return rc


def run_shell_command(cmd, env=os.environ, cwd=None, quiet=False, check_result=True):
    output_fn = output_subcmd
    if quiet:

        def noop(*args):
            pass

        output_fn = noop

    log_debug(f"Running: {cmd} with env {env}")
    rc = _sub_execute(cmd, env=env, cwd=cwd, stdout_cb=output_fn, stderr_cb=output_fn)
    log_debug(f"rc={rc} for {cmd}")
    if check_result and rc != 0:
        error_exit(f"{cmd} failed with rc={rc}")

    return rc


def include_exclude_check(s, include, exclude):
    if include is None and exclude is None:
        return True
    if include is not None:
        include_list = include.split(",")
        return s in include_list
    if exclude is not None:
        exclude_list = exclude.split(",")
        return s not in exclude_list


def get_stack_path(stack):
    if isinstance(stack, os.PathLike):
        return stack

    if stack_is_external(stack):
        if hasattr(stack, "file_path") and stack.file_path:
            stack_path = stack.file_path.parent
        elif hasattr(stack, "name") and stack.name:
            stack_path = Path(stack.name)
        else:
            stack_path = Path(stack)
    else:
        # In order to be compatible with Python 3.8 we need to use this hack to get the path:
        # See: https://stackoverflow.com/questions/25389095/python-get-path-of-root-project-structure
        stack_path = Path(__file__).absolute().parent.joinpath("data", "stacks", stack)
    return stack_path


def get_pod_list(parsed_stack):
    # Handle both old and new format
    pods = parsed_stack["pods"]
    if type(pods[0]) is str:
        result = pods
    else:
        result = []
        for pod in pods:
            result.append(pod["name"])
    return result


# # Find a config directory, looking first in any external stack
# and if not found there, internally
def resolve_config_dir(stack, config_dir_name: str):
    config_base = None
    if stack_is_external(stack):
        if stack.repo_path:
            config_base = stack.repo_path.joinpath("config")
        elif stack.file_path:
            config_base = stack.file_path.parent.parent.parent.joinpath("config")
        if config_base:
            proposed_dir = config_base.joinpath(config_dir_name)
            if proposed_dir.exists():
                return proposed_dir
        # If we don't find it fall through to the internal case
    config_base = get_internal_config_dir()
    return config_base.joinpath(config_dir_name)


# Find a compose file, looking first in any external stack
# and if not found there, internally
def resolve_compose_file(stack, pod_name: str):
    if stack_is_external(stack):
        # First try looking in the external stack for the compose file
        compose_base = Path(stack).parent.parent.joinpath("compose")
        proposed_file = compose_base.joinpath(f"{compose_file_prefix}-{pod_name}.yml")
        if proposed_file.exists():
            return proposed_file
        # If we don't find it fall through to the internal case
    compose_base = get_internal_compose_file_dir()
    return compose_base.joinpath(f"{compose_file_prefix}-{pod_name}.yml")


def get_internal_compose_file_dir():
    # TODO: refactor to use common code with deploy command
    # See: https://stackoverflow.com/questions/25389095/python-get-path-of-root-project-structure
    data_dir = Path(__file__).absolute().parent.joinpath("data")
    source_compose_dir = data_dir.joinpath("compose")
    return source_compose_dir


def get_internal_config_dir():
    # TODO: refactor to use common code with deploy command
    data_dir = Path(__file__).absolute().parent.joinpath("data")
    source_config_dir = data_dir.joinpath("config")
    return source_config_dir


def get_k8s_dir():
    data_dir = Path(__file__).absolute().parent.joinpath("data")
    source_config_dir = data_dir.joinpath("k8s")
    return source_config_dir


def get_parsed_deployment_spec(spec_file):
    spec_file_path = Path(spec_file)
    try:
        with spec_file_path:
            deploy_spec = get_yaml().load(open(spec_file_path, "r"))
            return deploy_spec
    except FileNotFoundError as error:
        # We try here to generate a useful diagnostic error
        log_error(f"Error: spec file: {spec_file_path} does not exist")
        error_exit(f"Exiting, error: {error}")


def stack_is_external(stack):
    if isinstance(stack, str) and stack == "webapp-template":
        # hack for the webapp template
        return False
    elif STACK_USE_BUILTIN_STACK and isinstance(stack, str):
        stack_path = Path(__file__).absolute().parent.joinpath("data", "stacks", stack)
        return not stack_path.exists()
    return True


def stack_is_in_deployment(stack: Path):
    if isinstance(stack, os.PathLike):
        return stack.joinpath(deployment_file_name).exists()
    else:
        return False


def get_yaml():
    # See: https://stackoverflow.com/a/45701840/1701505
    yaml = ruamel.yaml.YAML(typ=["rt", "string"])
    yaml.preserve_quotes = True
    yaml.indent(sequence=3, offset=1)
    return yaml


# TODO: this is fragile wrt to the subcommand depth
# See also: https://github.com/pallets/click/issues/108
def global_options(ctx):
    return ctx.parent.parent.obj


# TODO: hack
def global_options2(ctx):
    return ctx.parent.obj


def error_exit(s):
    log_error(f"ERROR: {s}")
    sys.exit(1)


def warn_exit(s):
    log_warn(f"WARN: {s}")
    sys.exit(0)


def env_var_map_from_file(file: Path, expand=True) -> Mapping[str, str]:
    return dotenv_values(file, interpolate=expand)


def check_if_stack_exists(stack):
    if not stack:
        error_exit("Error: Missing option '--stack'.")
    if stack and not stack_is_external(stack) and not STACK_USE_BUILTIN_STACK:
        error_exit(f"Stack {stack} does not exist")


def is_primitive(obj):
    primitives = (bool, str, int, float, type(None))
    return isinstance(obj, primitives)
