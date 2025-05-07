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

import click
import os
import random
import sys

from importlib import util
from pathlib import Path
from typing import List
from shutil import copy, copyfile, copytree
from secrets import token_hex
from stack import constants
from stack.opts import opts
from stack.util import (
    get_stack_path,
    get_yaml,
    pod_has_scripts,
    get_pod_script_paths,
    error_exit,
    env_var_map_from_file,
    resolve_config_dir,
)
from stack.deploy.deploy import create_deploy_context
from stack.deploy.spec import Spec, MergedSpec
from stack.deploy.stack import Stack, get_plugin_code_paths
from stack.deploy.deployer_factory import getDeployerConfigGenerator
from stack.deploy.deployment_context import DeploymentContext
from stack.util import global_options2


def _make_default_deployment_dir():
    return Path("deployment-001")


def _get_ports(stack):
    return stack.get_ports()


def _get_security_settings(stack):
    return stack.get_security_settings()


def _get_named_volumes(stack):
    return stack.get_named_volumes()


# If we're mounting a volume from a relatie path, then we
# assume the directory doesn't exist yet and create it
# so the deployment will start
# Also warn if the path is absolute and doesn't exist
def _create_bind_dir_if_relative(volume, path_string, compose_dir):
    path = Path(path_string)
    if not path.is_absolute():
        absolute_path = Path(compose_dir).parent.joinpath(path)
        absolute_path.mkdir(parents=True, exist_ok=True)
    else:
        if not path.exists():
            print(f"WARNING: mount path for volume {volume} does not exist: {path_string}")


# See: https://stackoverflow.com/questions/45699189/editing-docker-compose-yml-with-pyyaml
def _fixup_pod_file(pod, spec, compose_dir):
    deployment_type = spec[constants.deploy_to_key]
    # Fix up volumes
    if "volumes" in spec:
        spec_volumes = spec["volumes"]
        if "volumes" in pod:
            pod_volumes = pod["volumes"]
            for volume in pod_volumes.keys():
                if volume in spec_volumes:
                    volume_spec = spec_volumes[volume]
                    if volume_spec:
                        volume_spec_fixedup = volume_spec if Path(volume_spec).is_absolute() else f".{volume_spec}"
                        _create_bind_dir_if_relative(volume, volume_spec, compose_dir)
                        # this is Docker specific
                        if spec.is_docker_deployment():
                            new_volume_spec = {
                                "driver": "local",
                                "driver_opts": {
                                    "type": "none",
                                    "device": volume_spec_fixedup,
                                    "o": "bind",
                                },
                            }
                            pod["volumes"][volume] = new_volume_spec

    # Fix up configmaps
    if constants.configmaps_key in spec:
        if spec.is_kubernetes_deployment():
            spec_cfgmaps = spec[constants.configmaps_key]
            if "volumes" in pod:
                pod_volumes = pod[constants.volumes_key]
                for volume in pod_volumes.keys():
                    if volume in spec_cfgmaps:
                        volume_cfg = spec_cfgmaps[volume]
                        # Just make the dir (if necessary)
                        _create_bind_dir_if_relative(volume, volume_cfg, compose_dir)
        else:
            print(f"Warning: ConfigMaps not supported for {deployment_type}")

    # Fix up ports
    if "network" in spec and "ports" in spec["network"]:
        spec_ports = spec["network"]["ports"]
        for container_name, container_ports in spec_ports.items():
            if container_name in pod["services"]:
                pod["services"][container_name]["ports"] = container_ports


def _commands_plugin_paths(stack_name: str):
    plugin_paths = get_plugin_code_paths(stack_name)
    ret = [p.joinpath("hooks", "commands.py") for p in plugin_paths]
    return ret


# See: https://stackoverflow.com/a/54625079/1701505
def _has_method(o, name):
    return callable(getattr(o, name, None))


def call_stack_config_init(deploy_command_context, config_spec: Spec):
    # Link with the python file in the stack
    # Call a function in it
    # If no function found, return None
    python_file_paths = _commands_plugin_paths(deploy_command_context.stack)

    for python_file_path in python_file_paths:
        if python_file_path.exists():
            spec = util.spec_from_file_location("commands", python_file_path)
            imported_stack = util.module_from_spec(spec)
            spec.loader.exec_module(imported_stack)
            if _has_method(imported_stack, "init"):
                config_spec = imported_stack.init(deploy_command_context, config_spec)
    return config_spec


# TODO: fold this with function above
def call_stack_deploy_create(deploy_command_context, deployment_context):
    # Link with the python file in the stack
    # Call a function in it
    # If no function found, return None
    spec = deployment_context.spec
    if isinstance(spec, MergedSpec):
        stacks = spec.load_stacks()
    else:
        stacks = [spec.load_stack()]

    for stack in stacks:
        python_file_paths = _commands_plugin_paths(stack.name)
        for python_file_path in python_file_paths:
            if python_file_path.exists():
                spec = util.spec_from_file_location("commands", python_file_path)
                imported_stack = util.module_from_spec(spec)
                spec.loader.exec_module(imported_stack)
                if _has_method(imported_stack, "create"):
                    imported_stack.create(deploy_command_context, deployment_context, stack)


# Inspect the pod yaml to find config files referenced in subdirectories
# other than the one associated with the pod
def _find_extra_config_dirs(parsed_pod_file, pod):
    config_dirs = set()
    services = parsed_pod_file["services"]
    for service in services:
        service_info = services[service]
        if "volumes" in service_info:
            for volume in service_info["volumes"]:
                if ":" in volume:
                    host_path = volume.split(":")[0]
                    if host_path.startswith("../config"):
                        config_dir = host_path.split("/")[2]
                        if config_dir != pod:
                            config_dirs.add(config_dir)
        for env_file in service_info.get("env_file", []):
            if env_file.startswith("../config"):
                config_dir = env_file.split("/")[2]
                if config_dir != pod:
                    config_dirs.add(config_dir)
    return config_dirs


def _get_mapped_ports(stack: Stack, map_recipe: str):
    port_map_recipes = [
        "any-variable-random",
        "localhost-same",
        "any-same",
        "localhost-fixed-random",
        "any-fixed-random",
        "k8s-clusterip-same",
    ]
    ports = _get_ports(stack)
    if ports:
        # Implement any requested mapping recipe
        if map_recipe:
            if map_recipe in port_map_recipes:
                for service in ports.keys():
                    ports_array = ports[service]
                    for x in range(0, len(ports_array)):
                        orig_port = ports_array[x]
                        # Strip off any existing port mapping (eg, 5432:5432 becomes 5432)
                        unmapped_port = orig_port.split(":")[-1]
                        # Strip /udp suffix if present
                        bare_unmapped_port = unmapped_port.replace("/udp", "")
                        # limit to k8s NodePort range
                        random_port = random.randint(30000, 32767)  # Beware: we're relying on luck to not collide
                        if map_recipe in ["any-variable-random", "k8s-clusterip-same"]:
                            # default for docker and k8s
                            ports_array[x] = f"{unmapped_port}"
                        elif map_recipe == "localhost-same":
                            # Replace instances of "- XX" with "- 127.0.0.1:XX"
                            ports_array[x] = f"127.0.0.1:{bare_unmapped_port}:{unmapped_port}"
                        elif map_recipe == "any-same":
                            # Replace instances of "- XX" with "- 0.0.0.0:XX"
                            ports_array[x] = f"0.0.0.0:{bare_unmapped_port}:{unmapped_port}"
                        elif map_recipe == "localhost-fixed-random":
                            # Replace instances of "- XX" with "- 127.0.0.1:<rnd>:XX"
                            ports_array[x] = f"127.0.0.1:{random_port}:{unmapped_port}"
                        elif map_recipe == "any-fixed-random":
                            # Replace instances of "- XX" with "- 0.0.0.0:<rnd>:XX"
                            ports_array[x] = f"0.0.0.0:{random_port}:{unmapped_port}"
                        else:
                            print("Error: bad map_recipe")
            else:
                print(f"Error: --map-ports-to-host must specify one of: {port_map_recipes}")
                sys.exit(1)
    return ports


def _parse_config_variables(variable_values: str):
    result = None
    if variable_values:
        value_pairs = variable_values.split(",")
        if len(value_pairs):
            result_values = {}
            for value_pair in value_pairs:
                variable_value_pair = value_pair.split("=")
                if len(variable_value_pair) != 2:
                    print(f"ERROR: config argument is not valid: {variable_values}")
                    sys.exit(1)
                variable_name = variable_value_pair[0]
                variable_value = variable_value_pair[1]
                result_values[variable_name] = variable_value
            result = result_values
    return result


# The init command's implementation is in a separate function so that we can
# call it from other commands, bypassing the click decoration stuff
def init_operation(  # noqa: C901
    deploy_command_context,
    stack,
    deployer_type,
    config_variables,
    config_file,
    kube_config,
    image_registry,
    k8s_http_proxy,
    output,
    map_ports_to_host,
):
    spec_file_content = {"stack": stack, constants.deploy_to_key: deployer_type}
    if deployer_type in ["k8s", "k8s-kind"]:
        if kube_config:
            spec_file_content.update({constants.kube_config_key: kube_config})
        elif deployer_type == "k8s":
            error_exit("--kube-config must be supplied with --deploy-to k8s")
        if image_registry:
            spec_file_content.update({constants.image_registry_key: image_registry})
        elif deployer_type == "k8s":
            print("WARNING: --image-registry not specified, only default container registries (eg, Docker Hub) will be available")
        if k8s_http_proxy:
            proxy_hosts = {host for _, host, _, _ in map(_parse_http_proxy, k8s_http_proxy)}
            if len(proxy_hosts) != 1:
                error_exit(f"Only one host is allowed in --http-proxy at this time: {proxy_hosts}")

            issuers = {issuer if issuer else "letsencrypt-prod" for issuer, _, _, _ in map(_parse_http_proxy, k8s_http_proxy)}
            if len(issuers) != 1:
                error_exit(f"Only one cluster issuer is allowed in --http-proxy at this time: {issuers}")

            routes = [
                {constants.path_key: path, constants.proxy_to_key: proxy_to}
                for _, _, path, proxy_to in map(_parse_http_proxy, k8s_http_proxy)
            ]

            http_proxy = {
                constants.host_name_key: proxy_hosts.pop(),
                constants.cluster_issuer_key: issuers.pop(),
                constants.routes_key: routes,
            }
            if constants.network_key not in spec_file_content:
                spec_file_content[constants.network_key] = {}
            spec_file_content[constants.network_key].update({constants.http_proxy_key: [http_proxy]})
        else:
            print("WARNING: --http-proxy not specified, no external HTTP access will be configured.")
    else:
        # Check for --kube-config supplied for non-relevant deployer types
        if kube_config is not None:
            error_exit(f"--kube-config is not allowed with a {deployer_type} deployment")
        if image_registry is not None:
            error_exit(f"--image-registry is not allowed with a {deployer_type} deployment")
        if k8s_http_proxy:
            error_exit(f"--http-proxy is not allowed with a {deployer_type} deployment")
    # Implement merge, since update() overwrites
    if config_variables:
        orig_config = spec_file_content.get("config", {})
        new_config = config_variables
        merged_config = {**new_config, **orig_config}
        spec_file_content.update({"config": merged_config})
    if config_file:
        config_file_path = Path(config_file)
        if not config_file_path.exists():
            error_exit(f"config file: {config_file} does not exist")
        config_file_variables = env_var_map_from_file(config_file_path, expand=False)
        if config_file_variables:
            orig_config = spec_file_content.get("config", {})
            new_config = config_file_variables
            merged_config = {**new_config, **orig_config}
            spec_file_content.update({"config": merged_config})

    if not map_ports_to_host:
        if deployer_type in ["k8s", "k8s-kind"]:
            map_ports_to_host = "k8s-clusterip-same"
        elif deployer_type == "compose":
            map_ports_to_host = "any-variable-random"

    if map_ports_to_host and deployer_type == "k8s":
        if "k8s-" not in map_ports_to_host:
            error_exit(f"Error: --map-ports-to-host {map_ports_to_host} is not allowed with a {deployer_type} deployment ")

    parsed_stack = Stack(stack).init_from_file(os.path.join(get_stack_path(stack), constants.stack_file_name))
    ports = _get_mapped_ports(parsed_stack, map_ports_to_host)
    if constants.network_key in spec_file_content:
        proxy_targets = []
        if constants.http_proxy_key in spec_file_content[constants.network_key]:
            for entry in spec_file_content[constants.network_key][constants.http_proxy_key]:
                for r in entry[constants.routes_key]:
                    proxy_targets.append(r[constants.proxy_to_key])
        for target in proxy_targets:
            matched = False
            for svc in ports:
                for svc_port in ports[svc]:
                    svc_port = svc_port.split(":")[-1].replace("/udp", "")
                    if f"{svc}:{svc_port}" == target:
                        matched = True
                        break
            if not matched:
                print(f"WARN: Unable to match http-proxy target {target} to a ClusterIP service and port.")
        spec_file_content[constants.network_key][constants.ports_key] = ports
    else:
        spec_file_content.update({constants.network_key: {constants.ports_key: ports}})

    named_volumes = _get_named_volumes(parsed_stack)
    if named_volumes:
        volume_descriptors = {}
        configmap_descriptors = {}
        for named_volume in named_volumes["rw"]:
            if "k8s" in deployer_type:
                volume_descriptors[named_volume] = None
            else:
                volume_descriptors[named_volume] = f"./data/{named_volume}"
        for named_volume in named_volumes["ro"]:
            if "k8s" in deployer_type:
                if "config" in named_volume:
                    configmap_descriptors[named_volume] = f"./configmaps/{named_volume}"
                else:
                    volume_descriptors[named_volume] = None
            else:
                volume_descriptors[named_volume] = f"./data/{named_volume}"
        if volume_descriptors:
            spec_file_content["volumes"] = volume_descriptors
        if configmap_descriptors:
            spec_file_content["configmaps"] = configmap_descriptors

    security_settings = _get_security_settings(parsed_stack)
    if security_settings:
        spec_file_content[constants.security_key] = security_settings

    spec = call_stack_config_init(deploy_command_context, Spec(obj=spec_file_content))

    if opts.o.debug:
        print(f"Creating spec file for stack: {stack} with content: {spec}")

    spec.dump(output)


def _parse_http_proxy(raw_val: str):
    stripped = raw_val.replace("http://", "").replace("https://", "")
    cluster_issuer = None
    if "~" in stripped:
        cluster_issuer, stripped = stripped.split("~", 1)
    host, target = stripped.split(":", 1)
    route = "/"
    if "/" in host:
        host, route = host.split("/", 1)
        route = "/" + route

    return cluster_issuer, host, route, target


def _write_config_file(spec: Spec, config_env_file: Path):
    # Note: we want to write an empty file even if we have no config variables
    with open(config_env_file, "w") as output_file:
        config_vars = spec.get_config()
        if config_vars:
            for variable_name, variable_value in config_vars.items():
                output_file.write(f"{variable_name}={variable_value}\n")


def _write_kube_config_file(external_path: Path, internal_path: Path):
    if not external_path.exists():
        error_exit(f"Kube config file {external_path} does not exist")
    copyfile(external_path, internal_path)


def _copy_files_to_directory(file_paths: List[Path], directory: Path):
    for path in file_paths:
        # Using copy to preserve the execute bit
        copy(path, os.path.join(directory, os.path.basename(path)))


def _create_deployment_file(deployment_dir: Path, cluster=None):
    deployment_file_path = deployment_dir.joinpath(constants.deployment_file_name)
    if not cluster:
        cluster = f"{constants.cluster_name_prefix}{token_hex(8)}"
    with open(deployment_file_path, "w") as output_file:
        output_file.write(f"{constants.cluster_id_key}: {cluster}\n")


def _check_volume_definitions(spec):
    if spec.is_kubernetes_deployment():
        for volume_name, volume_path in spec.get_volumes().items():
            if volume_path:
                if not os.path.isabs(volume_path):
                    raise Exception(
                        f"Relative path {volume_path} for volume {volume_name} not "
                        f"supported for deployment type {spec.get_deployment_type()}"
                    )


@click.command()
@click.option("--cluster", help="specify a non-default cluster name")
@click.option("--spec-file", required=True, help="Spec file to use to create this deployment", multiple=True)
@click.option("--deployment-dir", help="Create deployment files in this directory")
@click.pass_context
def create(ctx, cluster, spec_file, deployment_dir):
    """deploy a stack"""

    if ctx.parent.obj.debug:
        print(f"ctx.parent.obj: {ctx.parent.obj}")

    ctx.obj = create_deploy_context(
        global_options2(ctx),
        None,
        None,
        None,
        None,
        cluster,
        None,
        None,
    )

    global_context = ctx.parent.obj
    if len(spec_file) == 1:
        spec = Spec().init_from_file(spec_file[0])
    else:
        spec = MergedSpec()
        for sf in spec_file:
            spec.merge(Spec().init_from_file(sf))

    if global_context.verbose:
        print(spec)

    deployment_command_context = ctx.obj
    return create_operation(
        deployment_command_context,
        spec,
        deployment_dir,
    )


# The init command's implementation is in a separate function so that we can
# call it from other commands, bypassing the click decoration stuff
def create_operation(deployment_command_context, parsed_spec: Spec | MergedSpec, deployment_dir):
    if opts.o.debug:
        print(f"parsed spec: {parsed_spec}")
    _check_volume_definitions(parsed_spec)

    deployment_type = parsed_spec[constants.deploy_to_key]

    # steps that we need no matter the spec type
    if deployment_dir is None:
        deployment_dir_path = _make_default_deployment_dir()
    else:
        deployment_dir_path = Path(deployment_dir)
    if deployment_dir_path.exists():
        error_exit(f"{deployment_dir_path} already exists")

    os.mkdir(deployment_dir_path)
    destination_compose_dir = deployment_dir_path.joinpath("compose")
    os.mkdir(destination_compose_dir)
    destination_pods_dir = deployment_dir_path.joinpath("pods")
    os.mkdir(destination_pods_dir)

    _create_deployment_file(deployment_dir_path, deployment_command_context.cluster_context.cluster)

    # Copy spec file into the deployment dir
    parsed_spec.dump(deployment_dir_path.joinpath(constants.spec_file_name))

    # Copy stack file into the deployment dir
    if isinstance(parsed_spec, MergedSpec):
        parsed_spec.merge_stacks().dump(deployment_dir_path.joinpath(constants.stack_file_name))
    else:
        parsed_spec.load_stack().dump(deployment_dir_path.joinpath(constants.stack_file_name))

    # Copy any config varibles from the spec file into an env file suitable for compose
    _write_config_file(parsed_spec, deployment_dir_path.joinpath(constants.config_file_name))

    # Copy any k8s config file into the deployment dir
    if deployment_type == "k8s":
        _write_kube_config_file(
            Path(parsed_spec.get_kube_config()),
            deployment_dir_path.joinpath(constants.kube_config_filename),
        )

    yaml = get_yaml()
    pods = parsed_spec.get_pod_list()
    for pod in pods:
        parsed_pod_file = parsed_spec.load_pod_file(pod)
        extra_config_dirs = _find_extra_config_dirs(parsed_pod_file, pod)
        destination_pod_dir = destination_pods_dir.joinpath(pod)
        os.mkdir(destination_pod_dir)
        if opts.o.debug:
            print(f"extra config dirs: {extra_config_dirs}")
        _fixup_pod_file(parsed_pod_file, parsed_spec, destination_compose_dir)

        if deployment_type == "compose":
            # Inject the shared config.env file into the compose file.  We don't need to do this for k8s.
            services = parsed_pod_file["services"]
            for service_name in services:
                service_info = services[service_name]
                shared_cfg_file = os.path.join(
                    "../" * len(destination_compose_dir.relative_to(deployment_dir_path).parts), constants.config_file_name
                )
                if "env_file" in service_info:
                    env_files = service_info["env_file"]
                    if isinstance(env_files, list):
                        service_info["env_file"] = [shared_cfg_file, *env_files]
                    else:
                        service_info["env_file"] = [shared_cfg_file, env_files]
                else:
                    service_info["env_file"] = [shared_cfg_file]

        with open(destination_compose_dir.joinpath(f"{constants.compose_file_prefix}-%s.yml" % pod), "w") as output_file:
            yaml.dump(parsed_pod_file, output_file)

        parsed_stack = parsed_spec.stack_for_pod(pod) if isinstance(parsed_spec, MergedSpec) else parsed_spec.load_stack()

        # Copy the config files for the pod, if any
        config_dirs = {pod}
        config_dirs = config_dirs.union(extra_config_dirs)
        for config_dir in config_dirs:
            source_config_dir = resolve_config_dir(parsed_stack.name, config_dir)
            if os.path.exists(source_config_dir):
                destination_config_dir = deployment_dir_path.joinpath("config", config_dir)
                # If the same config dir appears in multiple pods, it may already have been copied
                if not os.path.exists(destination_config_dir):
                    copytree(source_config_dir, destination_config_dir)
        # Copy the script files for the pod, if any
        if pod_has_scripts(parsed_stack, pod):
            destination_script_dir = destination_pod_dir.joinpath("scripts")
            os.mkdir(destination_script_dir)
            script_paths = get_pod_script_paths(parsed_stack, pod)
            _copy_files_to_directory(script_paths, destination_script_dir)
        if parsed_spec.is_kubernetes_deployment():
            for configmap in parsed_spec.get_configmaps():
                source_config_dir = resolve_config_dir(parsed_stack.name, configmap)
                if os.path.exists(source_config_dir):
                    destination_config_dir = deployment_dir_path.joinpath("configmaps", configmap)
                    copytree(source_config_dir, destination_config_dir, dirs_exist_ok=True)
        else:
            # TODO: We should probably only do this if the volume is marked :ro.
            for volume_name, volume_path in parsed_spec.get_volumes().items():
                source_config_dir = resolve_config_dir(parsed_stack.name, volume_name)
                # Only copy if the source exists and is _not_ empty.
                if os.path.exists(source_config_dir) and os.listdir(source_config_dir):
                    destination_config_dir = deployment_dir_path.joinpath(volume_path)
                    # Only copy if the destination exists and _is_ empty.
                    if os.path.exists(destination_config_dir) and not os.listdir(destination_config_dir):
                        copytree(
                            source_config_dir,
                            destination_config_dir,
                            dirs_exist_ok=True,
                        )

    # Delegate to the stack's Python code
    deployment_context = DeploymentContext()
    deployment_context.init(deployment_dir_path)
    # Bit of an hack, but we want to maintain the MergedSpec obj if we have it.
    deployment_context.spec = parsed_spec
    # Call the deployer to generate any deployer-specific files (e.g. for kind)
    deployer_config_generator = getDeployerConfigGenerator(deployment_type, deployment_context)
    # TODO: make deployment_dir_path a Path above
    deployer_config_generator.generate(deployment_dir_path)
    call_stack_deploy_create(deployment_command_context, deployment_context)
