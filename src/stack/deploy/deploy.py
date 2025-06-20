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

# Deploys the system components using a deployer (either docker-compose or k8s)

import copy
import os
import sys
import subprocess

from dataclasses import dataclass
from importlib import resources
from stack.config.util import get_dev_root_path
from stack.constants import compose_file_prefix
from stack.util import (
    include_exclude_check,
    stack_is_in_deployment,
    resolve_compose_file,
    error_exit
)
from stack.deploy.deployer import Deployer, DeployerException
from stack.deploy.deployer_factory import getDeployer
from stack.deploy.deploy_types import ClusterContext, DeployCommandContext
from stack.deploy.deployment_context import DeploymentContext
from stack.deploy.stack import Stack, get_parsed_stack_config


def create_deploy_context(
    global_context,
    deployment_context: DeploymentContext,
    stack,
    include,
    exclude,
    cluster,
    env_file,
    deploy_to,
) -> DeployCommandContext:
    # Extract the cluster name from the deployment, if we have one
    if deployment_context and cluster is None:
        cluster = deployment_context.get_cluster_id()
    cluster_context = _make_cluster_context(global_context, stack, include, exclude, cluster, env_file)
    deployer = getDeployer(
        deploy_to,
        deployment_context,
        compose_files=cluster_context.compose_files,
        compose_project_name=cluster_context.cluster,
        compose_env_file=cluster_context.env_file,
    )
    return DeployCommandContext(stack, cluster_context, deployer)


def up_operation(ctx, services_list, stay_attached=False, skip_cluster_management=False):
    global_context = ctx.parent.parent.obj
    deployment_cmd_context = ctx.obj
    cluster_context = deployment_cmd_context.cluster_context
    container_exec_env = _make_runtime_env(global_context)
    for attr, value in container_exec_env.items():
        os.environ[attr] = value
    if global_context.verbose:
        print(f"Running compose up with container_exec_env: {container_exec_env}, extra_args: {services_list}")
    for pre_start_command in cluster_context.pre_start_commands:
        _run_command(global_context, deployment_cmd_context, cluster_context, pre_start_command)
    deployment_cmd_context.deployer.up(
        detach=not stay_attached,
        skip_cluster_management=skip_cluster_management,
        services=services_list,
    )
    for post_start_command in cluster_context.post_start_commands:
        _run_command(global_context, deployment_cmd_context, cluster_context, post_start_command)
    _orchestrate_cluster_config(
        global_context,
        cluster_context.config,
        deployment_cmd_context.deployer,
        container_exec_env,
    )


def down_operation(ctx, delete_volumes, extra_args_list, skip_cluster_management=False):
    timeout_arg = None
    if extra_args_list:
        timeout_arg = extra_args_list[0]
    # Specify shutdown timeout (default 10s) to give services enough time to shutdown gracefully
    ctx.obj.deployer.down(
        timeout=timeout_arg,
        volumes=delete_volumes,
        skip_cluster_management=skip_cluster_management,
    )


def status_operation(ctx):
    ctx.obj.deployer.status()


def update_operation(ctx):
    ctx.obj.deployer.update()


def ps_operation(ctx):
    global_context = ctx.parent.parent.obj
    if not global_context.dry_run:
        container_list = ctx.obj.deployer.ps()
        if len(container_list) > 0:
            print("Running containers:")
            for container in container_list:
                print(f"id: {container.id}, name: {container.name}, ports: ", end="")
                ports = container.network_settings.ports
                comma = ""
                for port_mapping in ports.keys():
                    mapping = ports[port_mapping]
                    print(comma, end="")
                    if mapping is None:
                        print(f"{port_mapping}", end="")
                    else:
                        print(
                            f"{mapping[0]['HostIp']}:{mapping[0]['HostPort']}->{port_mapping}",
                            end="",
                        )
                    comma = ", "
                print()
        else:
            print("No containers running")


def port_operation(ctx, extra_args):
    global_context = ctx.parent.parent.obj
    extra_args_list = list(extra_args) or None
    if not global_context.dry_run:
        if extra_args_list is None or len(extra_args_list) < 2:
            print("Usage: port <service> <exposed-port>")
            sys.exit(1)
        service_name = extra_args_list[0]
        exposed_port = extra_args_list[1]
        if global_context.verbose:
            print(f"Running compose port {service_name} {exposed_port}")
        mapped_port_data = ctx.obj.deployer.port(service_name, exposed_port)
        if mapped_port_data:
            print(f"{mapped_port_data[0]}:{mapped_port_data[1]}")


def exec_operation(ctx, extra_args):
    global_context = ctx.parent.parent.obj
    extra_args_list = list(extra_args) or None
    if not global_context.dry_run:
        if extra_args_list is None or len(extra_args_list) < 2:
            print("Usage: exec <service> <cmd>")
            sys.exit(1)
        service_name = extra_args_list[0]
        command_to_exec = ["sh", "-c"] + extra_args_list[1:]
        container_exec_env = _make_runtime_env(global_context)
        if global_context.verbose:
            print(f"Running compose exec {service_name} {command_to_exec}")
        try:
            ctx.obj.deployer.execute(service_name, command_to_exec, envs=container_exec_env, tty=True)
        except DeployerException:
            print("container command returned error exit status")


def logs_operation(ctx, tail: int, follow: bool, extra_args: str):
    extra_args_list = list(extra_args) or None
    services_list = extra_args_list if extra_args_list is not None else []
    logs_stream = ctx.obj.deployer.logs(services=services_list, tail=tail, follow=follow, stream=True)
    for stream_type, stream_content in logs_stream:
        print(stream_content.decode("utf-8"), end="")


def get_stack_status(ctx, stack):
    ctx_copy = copy.copy(ctx)
    ctx_copy.stack = stack

    cluster_context = _make_cluster_context(ctx_copy, stack, None, None, None, None)
    deployer = Deployer(
        compose_files=cluster_context.compose_files,
        compose_project_name=cluster_context.cluster,
    )
    # TODO: refactor to avoid duplicating this code above
    if ctx.verbose:
        print("Running compose ps")
    container_list = deployer.ps()
    if len(container_list) > 0:
        if ctx.debug:
            print(f"Container list from compose ps: {container_list}")
        return True
    else:
        if ctx.debug:
            print("No containers found from compose ps")
        False


def _make_runtime_env(ctx):
    container_exec_env = {
        "STACK_HOST_UID": f"{os.getuid()}",
        "STACK_HOST_GID": f"{os.getgid()}",
    }
    container_exec_env.update({"STACK_SCRIPT_DEBUG": "true"} if ctx.debug else {})
    return container_exec_env


# stack has to be either PathLike pointing to a stack yml file, or a string with the name of a known stack
def _make_cluster_context(ctx, stack, include, exclude, cluster, env_file):
    dev_root_path = get_dev_root_path()

    # TODO: hack, this should be encapsulated by the deployment context.
    deployment = stack_is_in_deployment(stack)
    if not deployment:
        error_exit("cluster context must be in a deployment")

    compose_dir = stack.joinpath("compose")

    # See: https://stackoverflow.com/a/20885799/1701505
    from stack import data

    with resources.open_text(data, "pod-list.txt") as pod_list_file:
        all_pods = pod_list_file.read().splitlines()

    pods_in_scope = []
    stack_config = Stack(stack)
    if stack:
        stack_config = get_parsed_stack_config(stack)
        pods_in_scope = stack_config.get_pods()
        cluster_config = stack_config["config"] if "config" in stack_config else None
    else:
        pods_in_scope = all_pods
        cluster_config = None

    # Convert all pod definitions to v1.1 format
    pods_in_scope = _convert_to_new_format(pods_in_scope)
    if ctx.verbose:
        print(f"Pods: {pods_in_scope}")

    # Construct a docker compose command suitable for our purpose

    compose_files = []
    pre_start_commands = []
    post_start_commands = []
    for pod in pods_in_scope:
        pod_name = pod["name"]
        pod_repository = pod.get("repository", stack_config.get_repo_name())
        if include_exclude_check(pod_name, include, exclude):
            if pod_repository is None or pod_repository == "internal":
                compose_file_name = os.path.join(compose_dir, f"{compose_file_prefix}-{pod_name}.yml")
            else:
                compose_file_name = os.path.join(compose_dir, f"{compose_file_prefix}-{pod_name}.yml")
                pod_pre_start_command = pod.get("pre_start_command")
                pod_post_start_command = pod.get("post_start_command")
                script_dir = compose_dir.parent.joinpath("pods", pod_name, "scripts")
                if pod_pre_start_command is not None:
                    pre_start_commands.append(os.path.join(script_dir, pod_pre_start_command))
                if pod_post_start_command is not None:
                    post_start_commands.append(os.path.join(script_dir, pod_post_start_command))
            compose_files.append(compose_file_name)
        else:
            if ctx.verbose:
                print(f"Excluding: {pod_name}")

    if ctx.verbose:
        print(f"files: {compose_files}")

    return ClusterContext(
        cluster,
        compose_files,
        pre_start_commands,
        post_start_commands,
        cluster_config,
        env_file,
    )


def _convert_to_new_format(old_pod_array):
    new_pod_array = []
    for old_pod in old_pod_array:
        if isinstance(old_pod, dict):
            new_pod_array.append(old_pod)
        else:
            new_pod = {"name": old_pod, "repository": "internal", "path": old_pod}
            new_pod_array.append(new_pod)
    return new_pod_array


def _run_command(ctx, deployment_cmd_ctx, cluster_ctx, command):
    if ctx.verbose:
        print(f"Running command: {command}")
    command_dir = os.path.dirname(command)
    command_file = os.path.join(".", os.path.basename(command))
    command_env = os.environ.copy()
    command_env["STACK_COMPOSE_PROJECT"] = cluster_ctx.cluster
    command_env["STACK_DEPLOYMENT_DIR"] = deployment_cmd_ctx.stack
    if ctx.debug:
        command_env["STACK_SCRIPT_DEBUG"] = "true"
    command_result = subprocess.run(command_file, shell=True, env=command_env, cwd=command_dir)
    if command_result.returncode != 0:
        print(f"FATAL Error running command: {command}")
        sys.exit(1)


def _orchestrate_cluster_config(ctx, cluster_config, deployer, container_exec_env):
    @dataclass
    class ConfigDirective:
        source_container: str
        source_variable: str
        destination_container: str
        destination_variable: str

    if cluster_config is not None:
        for container in cluster_config:
            container_config = cluster_config[container]
            if ctx.verbose:
                print(f"{container} config: {container_config}")
            for directive in container_config:
                pd = ConfigDirective(
                    container_config[directive].split(".")[0],
                    container_config[directive].split(".")[1],
                    container,
                    directive,
                )
                if ctx.verbose:
                    print(
                        f"Setting {pd.destination_container}.{pd.destination_variable}"
                        f" = {pd.source_container}.{pd.source_variable}"
                    )
                # TODO: add a timeout
                waiting_for_data = True
                destination_output = "*** no output received yet ***"
                while waiting_for_data:
                    # TODO: fix the script paths so they're consistent between containers
                    source_value = None
                    try:
                        source_value = deployer.execute(
                            pd.source_container,
                            [
                                "sh",
                                "-c",
                                "sh /docker-entrypoint-scripts.d/export-" f"{pd.source_variable}.sh",
                            ],
                            tty=False,
                            envs=container_exec_env,
                        )
                    except DeployerException as error:
                        if ctx.debug:
                            print(f"Docker exception reading config source: {error}")
                        # If the script executed failed for some reason, we get:
                        # "It returned with code 1"
                        if "It returned with code 1" in str(error):
                            if ctx.verbose:
                                print("Config export script returned an error, re-trying")
                        # If the script failed to execute (e.g. the file is not there) then we get:
                        # "It returned with code 2"
                        if "It returned with code 2" in str(error):
                            print(f"Fatal error reading config source: {error}")
                    if source_value:
                        if ctx.debug:
                            print(f"fetched source value: {source_value}")
                        destination_output = deployer.execute(
                            pd.destination_container,
                            [
                                "sh",
                                "-c",
                                f"sh /scripts/import-{pd.destination_variable}.sh" f" {source_value}",
                            ],
                            tty=False,
                            envs=container_exec_env,
                        )
                        waiting_for_data = False
                    if ctx.debug and not waiting_for_data:
                        print(f"destination output: {destination_output}")
