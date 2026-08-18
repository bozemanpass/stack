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
import json
import os
import random

from importlib import util
from pathlib import Path
from secrets import token_hex
from shutil import copy, copyfile, copytree
from typing import List

from stack import constants
from stack.build.build_util import read_stack_locks
from stack.build.image_pins import apply_image_locks_to_pod_file
from stack.deploy.compose.helpers import add_env_var
from stack.deploy.backup import backup_settings
from stack.log import log_debug, log_warn, log_info
from stack.util import (
    get_stack_path,
    get_yaml,
    error_exit,
    env_var_map_from_file,
    resolve_config_dir,
)
from stack.deploy.deploy import create_deploy_context
from stack.deploy.kube_config import is_deferred_reference, validate_reference
from stack.deploy import secrets as stack_secrets
from stack.deploy.spec import Spec, MergedSpec, load_spec
from stack.deploy.stack import Stack, get_plugin_code_paths, get_pod_script_paths, pod_has_scripts
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
            log_warn(f"WARN: mount path for volume {volume} does not exist: {path_string}")


# See: https://stackoverflow.com/questions/45699189/editing-docker-compose-yml-with-pyyaml
def _fixup_pod_file(pod, spec, compose_dir):
    deployment_type = spec[constants.deploy_to_key]
    # Fix up volumes
    if "volumes" in spec:
        # Through the accessor rather than the raw object: a volume entry may be
        # the mapping form, and what this pass needs is the path.
        spec_volumes = spec.get_volumes()
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
            log_warn(f"Warning: ConfigMaps not supported for {deployment_type}")

    # Fix up ports
    if "network" in spec and "ports" in spec["network"]:
        spec_ports = spec["network"]["ports"]
        for container_name, container_ports in spec_ports.items():
            if container_name in pod["services"]:
                pod["services"][container_name]["ports"] = container_ports


def _commands_plugin_paths(stack: str):
    plugin_paths = get_plugin_code_paths(stack)
    ret = [p.joinpath("deploy", "commands.py") for p in plugin_paths]
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
        python_file_paths = _commands_plugin_paths(stack)
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
                            error_exit("bad map_recipe")
            else:
                error_exit(f"--map-ports-to-host must specify one of: {port_map_recipes}")
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
                    error_exit(f"config argument is not valid: {variable_values}")
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
    http_proxy_fqdn,
    http_proxy_clusterissuer,
    http_proxy_targets,
    output,
    map_ports_to_host,
    backup_targets=None,
    clusterissuer_explicitly_set=False,
    secret_variables=None,
):
    spec_file_content = {"stack": stack, constants.deploy_to_key: deployer_type}
    if deployer_type in ["k8s", "k8s-kind"]:
        if kube_config:
            validate_reference(kube_config)
            spec_file_content.update({constants.kube_config_key: kube_config})
        elif deployer_type == "k8s":
            error_exit("--kube-config must be supplied with --deploy-to k8s")
        if image_registry:
            spec_file_content.update({constants.image_registry_key: image_registry})
        elif deployer_type == "k8s":
            log_warn(
                "WARN: --image-registry not specified: locally built images can only be deployed"
                " if they are published to a container registry the cluster can reach"
            )
    else:
        # Check for --kube-config supplied for non-relevant deployer types
        if kube_config is not None:
            error_exit(f"--kube-config is not allowed with a {deployer_type} deployment")

    if http_proxy_targets:
        routes = []
        for target in http_proxy_targets:
            routes.append(
                {
                    constants.path_key: target["path"],
                    constants.proxy_to_key: f"{target['service']}:{target['port']}",
                }
            )
        http_proxy = {
            constants.host_name_key: http_proxy_fqdn,
            constants.routes_key: routes,
        }
        if deployer_type in ["k8s", "k8s-kind"]:
            if http_proxy_clusterissuer:
                http_proxy[constants.cluster_issuer_key] = http_proxy_clusterissuer
        elif clusterissuer_explicitly_set:
            # Only worth saying when the user actually asked for a cluster issuer: the
            # option carries a default, so testing its value would flag every non-k8s
            # deployment, which is the ordinary case and not something to report.
            log_info("NOTE: --http-proxy-clusterissuer is only used when deploying to Kubernetes; ignoring it")
        if constants.network_key not in spec_file_content:
            spec_file_content[constants.network_key] = {}
        spec_file_content[constants.network_key].update({constants.http_proxy_key: [http_proxy]})

    # Record backup annotations (e.g. excluded volumes) parsed from the stack's composefiles.
    if backup_targets and (backup_targets.get("exclude") or backup_targets.get("commands")):
        spec_file_content[constants.backup_key] = backup_targets

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

    # The stack declares which env vars are secret; the spec records where each
    # value comes from -- `generate`, or a reference -- and never the value itself.
    declared_secrets = stack_secrets.declared_secrets(parsed_stack)
    secret_variables = dict(secret_variables or {})
    secret_entries = {}
    for secret_name, declaration in declared_secrets.items():
        if secret_name in secret_variables:
            secret_entries[secret_name] = secret_variables.pop(secret_name)
        elif declaration.get("external"):
            # A generated value would be useless here -- the secret's counterpart
            # lives outside the deployment -- so a reference has to be recorded
            # now: there is no later point at which one could be.
            error_exit(
                f"secret {secret_name} is declared external by the stack; supply a reference "
                f"with --secret {secret_name}=env:VAR_NAME (or file:, env-file:, exec:)"
            )
        else:
            secret_entries[secret_name] = stack_secrets.GENERATE
    # --secret names the stack does not declare are allowed, like extra --config vars.
    secret_entries.update(secret_variables)
    for secret_name, secret_value in secret_entries.items():
        stack_secrets.validate_secret_entry(secret_name, secret_value)
        if secret_name in spec_file_content.get("config", {}):
            error_exit(f"{secret_name} is declared as a secret and may not also be set with --config")
    if secret_entries:
        spec_file_content[constants.secrets_key] = secret_entries

    ports = _get_mapped_ports(parsed_stack, map_ports_to_host)
    if constants.network_key in spec_file_content:
        spec_file_content[constants.network_key][constants.ports_key] = ports
    else:
        spec_file_content.update({constants.network_key: {constants.ports_key: ports}})

    named_volumes = _get_named_volumes(parsed_stack)
    if named_volumes:
        volume_descriptors = {}
        configmap_descriptors = {}
        # A volume's data lives in ./data/<name> under the deployment directory,
        # for kind as well as compose: the kind cluster bind mounts that directory
        # into its node (see _generate_kind_mounts), so the data outlives the
        # cluster -- which matters because stopping a kind deployment deletes it.
        #
        # A remote cluster is the exception, being the one target whose data cannot
        # live in the deployment directory. There the volume is left unmapped, which
        # gets it a PVC from the cluster's default storage class.
        data_is_local = deployer_type != constants.k8s_deploy_type
        for named_volume in named_volumes["rw"]:
            volume_descriptors[named_volume] = f"./data/{named_volume}" if data_is_local else None
        for named_volume in named_volumes["ro"]:
            if "k8s" in deployer_type and "config" in named_volume:
                configmap_descriptors[named_volume] = f"./configmaps/{named_volume}"
            else:
                volume_descriptors[named_volume] = f"./data/{named_volume}" if data_is_local else None
        if volume_descriptors:
            spec_file_content["volumes"] = volume_descriptors
        if configmap_descriptors:
            spec_file_content["configmaps"] = configmap_descriptors

    security_settings = _get_security_settings(parsed_stack)
    if security_settings:
        spec_file_content[constants.security_key] = security_settings

    spec = call_stack_config_init(deploy_command_context, Spec(obj=spec_file_content))

    log_debug(f"Creating spec file for stack: {stack} with content: {spec}")

    if output:
        spec.dump(output)
    return spec


def _remove_secret_environment_literals(service_info, secret_names):
    # A literal a stack's compose file still carries for a now-declared secret
    # (e.g. a default password) would both leak into the generated compose file
    # and, being an `environment:` entry, override the injected value.  The
    # declaration wins: the literal is dropped from the deployment's copy.
    env = service_info.get("environment")
    if not env:
        return
    if isinstance(env, dict):
        for name in secret_names:
            env.pop(name, None)
    else:
        service_info["environment"] = [e for e in env if str(e).split("=", 1)[0] not in secret_names]


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
    return cluster


def _check_volume_definitions(spec):
    # A remote cluster's volume path is a path on one of its nodes, so it has to be
    # absolute -- there is nothing sensible to resolve it against. A kind cluster's
    # node runs on this machine, and a relative path is resolved against the
    # deployment directory when its bind mount is generated
    # (_make_absolute_host_path), so ./data/<name> works there and is what init writes.
    remote_k8s = spec.is_kubernetes_deployment() and not spec.is_kind_deployment()
    for volume_name, volume_path in spec.get_volumes().items():
        if remote_k8s and volume_path and not os.path.isabs(volume_path):
            raise Exception(
                f"Relative path {volume_path} for volume {volume_name} not "
                f"supported for deployment type {spec.get_deployment_type()}"
            )
        affinity = spec.get_volume_affinity(volume_name)
        if affinity is None:
            continue
        # An affinity names the node(s) holding the volume's data, so it means
        # nothing without a path, and nothing at all on a target whose volumes
        # live on this machine.  Rejected rather than ignored: an affinity that
        # silently did nothing would look exactly like one that worked.
        if not remote_k8s:
            raise Exception(
                f"Affinity for volume {volume_name} not supported for deployment type {spec.get_deployment_type()}"
            )
        if not volume_path:
            raise Exception(f"Affinity for volume {volume_name} requires a path")
        if not isinstance(affinity, dict) or not affinity.get("label") or not affinity.get("value"):
            raise Exception(f"Affinity for volume {volume_name} must specify label and value")


def _check_runtime_class(spec):
    # A RuntimeClass is a k8s object, so naming one on a compose deployment cannot
    # mean anything.  Rejected rather than ignored, on the same reasoning as the
    # volume affinity above: a spec asking for a sandboxed runtime and silently
    # getting an ordinary container looks exactly like one that worked, and the
    # whole point of asking was the isolation.
    config = spec.obj.get(constants.runtime_class_key)
    if config is None:
        return
    if not spec.is_kubernetes_deployment():
        raise Exception(f"{constants.runtime_class_key} not supported for deployment type {spec.get_deployment_type()}")
    if not isinstance(config, dict):
        raise Exception(f"{constants.runtime_class_key} must be a mapping of default and/or {constants.services_key}")
    unknown = set(config.keys()) - {"default", constants.services_key}
    if unknown:
        raise Exception(f"Unknown key(s) {sorted(unknown)} in {constants.runtime_class_key}")
    services = config.get(constants.services_key, {})
    if not isinstance(services, dict):
        raise Exception(f"{constants.runtime_class_key}.{constants.services_key} must be a mapping of service name to class")
    for name, value in list(services.items()) + [("default", config.get("default"))]:
        if value is not None and not isinstance(value, str):
            raise Exception(f"Runtime class for {name} must be a string naming a RuntimeClass on the cluster")

    # A sandboxed runtime runs the container inside a guest VM with its own kernel,
    # where the host privileges `privileged: true` asks for are not the host's.  The
    # combination is very unlikely to be what the author meant, so say so rather than
    # leaving them to debug it inside the guest.
    for service_name in spec.obj.get(constants.security_key, {}):
        if spec.get_privileged(service_name) and spec.get_runtime_class(service_name):
            raise Exception(
                f"Service {service_name} cannot be both privileged and run under "
                f"runtime class {spec.get_runtime_class(service_name)}"
            )


@click.command()
@click.option("--cluster", help="specify a non-default cluster name")
@click.option("--spec-file", required=True, help="Spec file to use to create this deployment", multiple=True)
@click.option("--deployment-dir", help="Create deployment files in this directory")
@click.pass_context
def create(ctx, cluster, spec_file, deployment_dir):
    """deploy a stack"""

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

    if len(spec_file) == 1:
        spec = load_spec(spec_file[0])
    else:
        spec = MergedSpec()
        for sf in spec_file:
            spec.merge(load_spec(sf))

    log_debug(spec)

    deployment_command_context = ctx.obj
    return create_operation(
        deployment_command_context,
        spec,
        deployment_dir,
    )


# The init command's implementation is in a separate function so that we can
# call it from other commands, bypassing the click decoration stuff
def create_operation(deployment_command_context, parsed_spec: Spec | MergedSpec, deployment_dir):  # noqa: C901
    log_debug(f"parsed spec: {parsed_spec}")
    _check_volume_definitions(parsed_spec)
    _check_runtime_class(parsed_spec)
    # Validated here as well as at init, since a spec file is edited by hand.
    stack_secrets.validate_spec_secrets(parsed_spec)

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
    # pods/<pod>/scripts/ holds a pod's pre/post-start hook scripts, and is created
    # below only for a pod that declares one -- an empty pods/<pod> next to every
    # deployment was a puzzle worth more than it was worth (#128).
    destination_pods_dir = deployment_dir_path.joinpath("pods")

    deployment_command_context.cluster_context.cluster = _create_deployment_file(
        deployment_dir_path, deployment_command_context.cluster_context.cluster
    )

    # Copy spec file into the deployment dir
    parsed_spec.dump(deployment_dir_path.joinpath(constants.spec_file_name))

    # Copy stack file into the deployment dir
    if isinstance(parsed_spec, MergedSpec):
        parsed_spec.merge_stacks().dump(deployment_dir_path.joinpath(constants.stack_file_name))
    else:
        parsed_spec.load_stack().dump(deployment_dir_path.joinpath(constants.stack_file_name))

    # Copy any config variables from the spec file into an env file suitable for compose
    _write_config_file(parsed_spec, deployment_dir_path.joinpath(constants.config_file_name))

    # Copy any k8s config file into the deployment dir.  A spec that names its
    # credential by reference rather than by path gets nothing copied in: the
    # reference travels in the spec file and is resolved when the deployer
    # connects, which is what keeps the credential out of a deployment that is
    # going to be committed to git.
    if deployment_type == "k8s":
        kube_config = parsed_spec.get_kube_config()
        if not kube_config:
            error_exit(f"{constants.kube_config_key} is required for a k8s deployment")
        validate_reference(kube_config)
        if not is_deferred_reference(kube_config):
            _write_kube_config_file(
                Path(kube_config),
                deployment_dir_path.joinpath(constants.kube_config_filename),
            )

    yaml = get_yaml()
    pods = parsed_spec.get_pod_list()
    for pod in pods:
        parsed_pod_file = parsed_spec.load_pod_file(pod)
        extra_config_dirs = _find_extra_config_dirs(parsed_pod_file, pod)
        destination_pod_dir = destination_pods_dir.joinpath(pod)
        log_debug(f"extra config dirs: {extra_config_dirs}")
        parsed_stack = parsed_spec.stack_for_pod(pod) if isinstance(parsed_spec, MergedSpec) else parsed_spec.load_stack()
        # The deployment's copy of the pod file pulls each external image by the digest
        # recorded in the stack's lock file, when there is one (see build/image_pins.py).
        # Except on kind, whose images arrive by side-load rather than by pull: `kind
        # load` re-serializes through a docker archive, which cannot reproduce the
        # registry's manifest digest, so a by-digest pod spec is unsatisfiable there.
        if parsed_stack.file_path and deployment_type != constants.k8s_kind_deploy_type:
            image_locks = read_stack_locks(parsed_stack.file_path.parent)["images"]
            if image_locks:
                apply_image_locks_to_pod_file(parsed_pod_file, image_locks)
        _fixup_pod_file(parsed_pod_file, parsed_spec, destination_compose_dir)

        # On every target: the deployment's copy of the pod file must not carry a
        # cleartext value for anything the stack declares secret.
        if parsed_spec.get_secrets():
            for service_info in parsed_pod_file.get(constants.services_key, {}).values():
                _remove_secret_environment_literals(service_info, list(parsed_spec.get_secrets()))

        # The backup stack fills a gap that only the Docker target has: on
        # Kubernetes the backup engine is K8up, configured by the deployer from
        # the same ambient settings, and a backup container deployed there would
        # sit idle holding no data mounts.
        if parsed_spec.is_kubernetes_deployment() and constants.backup_service_name in parsed_pod_file.get(
            constants.services_key, {}
        ):
            log_warn(
                "WARN: the backup stack is a Docker-target mix-in and does nothing on Kubernetes, "
                "where backups are run by K8up (see docs/backup.md)"
            )

        if deployment_type == "compose":
            # Inject the shared config.env file into the compose file.  We don't need to do this for k8s.
            services = parsed_pod_file["services"]
            for service_name in services:
                service_info = services[service_name]
                image_name = service_info["image"]
                if image_name.endswith(":stack"):
                    service_info["image"] = image_name[:-5] + deployment_command_context.cluster_context.cluster

                relative_prefix = "../" * len(destination_compose_dir.relative_to(deployment_dir_path).parts)
                shared_env_files = [os.path.join(relative_prefix, constants.config_file_name)]
                # Generated secrets live beside config.env in secrets.env (written
                # by the deployer config generator, 0600 and gitignored), listed
                # after it so a secret wins over a config value of the same name.
                generated_secret_names = stack_secrets.generated_names(parsed_spec)
                referenced_secrets = stack_secrets.referenced_entries(parsed_spec)
                if generated_secret_names:
                    shared_env_files.append(os.path.join(relative_prefix, constants.secrets_file_name))
                if "env_file" in service_info:
                    env_files = service_info["env_file"]
                    if isinstance(env_files, list):
                        service_info["env_file"] = [*shared_env_files, *env_files]
                    else:
                        service_info["env_file"] = [*shared_env_files, env_files]
                else:
                    service_info["env_file"] = shared_env_files

                if referenced_secrets:
                    # A referenced secret is never persisted in the deployment: the
                    # compose file interpolates a variable the deployer exports for
                    # the duration of an up, from the reference resolved just then.
                    svc_env = service_info.get("environment", {})
                    for secret_name in referenced_secrets:
                        add_env_var(secret_name, f"${{{stack_secrets.shell_var(secret_name)}:-}}", svc_env)
                    service_info["environment"] = svc_env

                http_proxy_config = parsed_spec.get_http_proxy()
                for pxy in http_proxy_config:
                    svc_env = service_info.get("environment", {})
                    host = pxy[constants.host_name_key]
                    vhost = {host: {}}
                    for r in pxy[constants.routes_key]:
                        pxy_svc, pxy_port = r[constants.proxy_to_key].split(":", 1)
                        if pxy_svc == service_name:
                            path = "/" + r[constants.path_key].strip("/")
                            # A plain prefix, with the stripping of that prefix expressed
                            # as the destination: nginx-proxy emits
                            # "location <path> { proxy_pass http://<upstream><dest>; }",
                            # and a proxy_pass whose URI part is "/" is nginx's own way of
                            # replacing the matched prefix rather than appending to it.  So
                            # a request for /api/todos/1 reaches the service as /1, and the
                            # root path proxies through unchanged.
                            #
                            # Not an nginx regex location (~ ^/api/todos(?:/(.*))?$ with a
                            # dest of /$1), which is what this used to emit: nginx-proxy
                            # takes these keys as prefixes and skips any that does not begin
                            # with "/", so a regex route was dropped from the generated
                            # configuration without a word about it.  What that looks like
                            # is a service that is up and healthy and answers nothing --
                            # the request lands on whichever route did survive, usually
                            # the frontend at "/".
                            vhost[host][path] = {
                                "dest": "/",
                                "port": pxy_port,
                            }

                    if vhost[host]:
                        add_env_var("VIRTUAL_HOST_MULTIPORTS", json.dumps(vhost), svc_env)
                        if "localhost" != host and "." in host:
                            add_env_var("LETSENCRYPT_HOST", host, svc_env)
                        service_info["environment"] = svc_env

                # When backup is enabled, augment the backup service (defined in the mixed-in
                # backup-stack) with read-only mounts of the deployment's data volumes plus the
                # backup engine configuration. Mirrors the VIRTUAL_HOST injection above.
                # See docs/backup-implementation.md.
                if service_name == constants.backup_service_name:
                    settings = backup_settings()
                    if settings.enabled:
                        backup_cfg = parsed_spec.get_backup()
                        exclude = set(backup_cfg.get("exclude", []))
                        mounts = service_info.setdefault("volumes", [])
                        for vol_name, vol_path in parsed_spec.get_volumes().items():
                            if vol_name in exclude or not vol_path:
                                continue
                            # Same host path the named volume binds to (see _fixup_pod_file).
                            # Mounted rw so the same container can restore in place; scheduled
                            # backups only read. See docs/backup.md "Restore".
                            #
                            # /data/<volume> is where K8up mounts a claim in its own backup
                            # job, so the path recorded inside a snapshot is the same on both
                            # targets -- which is what lets either target restore a
                            # repository the other wrote.
                            device = vol_path if Path(vol_path).is_absolute() else f".{vol_path}"
                            mounts.append(f"{device}:/data/{vol_name}:rw")
                        backup_env = service_info.get("environment", {})
                        deployment_name = deployment_command_context.cluster_context.cluster
                        # The restic host the snapshots are filed under.
                        add_env_var("STACK_DEPLOYMENT", deployment_name, backup_env)
                        add_env_var("BACKUP_S3_ENDPOINT", settings.s3_endpoint, backup_env)
                        # Each deployment gets its own repository inside the
                        # configured bucket, as it does on Kubernetes (see
                        # k8s/k8up.py backend_spec for why they are kept apart).
                        add_env_var(
                            "BACKUP_S3_BUCKET",
                            f"{settings.s3_bucket.rstrip('/')}/{deployment_name}",
                            backup_env,
                        )
                        add_env_var("BACKUP_SCHEDULE", settings.schedule, backup_env)
                        add_env_var("BACKUP_RETENTION", settings.retention, backup_env)
                        # Consistency dumps from `@stack backup-command`, in the format
                        # run-hooks.sh in the backup image parses: one entry per line,
                        # "<service> <extension> <command...>".  The command is the tail
                        # of the line, so it may contain anything but a newline.
                        backup_commands = backup_cfg.get("commands", {})
                        if backup_commands:
                            hooks = "\n".join(
                                f"{svc} {info.get('file-extension') or constants.backup_default_file_extension} {info['command']}"
                                for svc, info in backup_commands.items()
                            )
                            add_env_var("BACKUP_PRE_HOOKS", hooks, backup_env)
                        # restic's own environment variables. Only set from the
                        # ambient settings when they are configured, so that a
                        # deployment supplying them another way (through the
                        # shared config.env) keeps working.
                        if settings.restic_password:
                            add_env_var("RESTIC_PASSWORD", settings.restic_password, backup_env)
                        if settings.s3_key_id:
                            add_env_var("AWS_ACCESS_KEY_ID", settings.s3_key_id, backup_env)
                        if settings.s3_key:
                            add_env_var("AWS_SECRET_ACCESS_KEY", settings.s3_key, backup_env)
                        service_info["environment"] = backup_env

        with open(destination_compose_dir.joinpath(f"{constants.compose_file_prefix}-%s.yml" % pod), "w") as output_file:
            yaml.dump(parsed_pod_file, output_file)

        # Copy the config files for the pod, if any
        config_dirs = {pod}
        config_dirs = config_dirs.union(extra_config_dirs)
        for config_dir in config_dirs:
            source_config_dir = resolve_config_dir(parsed_stack, config_dir)
            if os.path.exists(source_config_dir):
                destination_config_dir = deployment_dir_path.joinpath("config", config_dir)
                # If the same config dir appears in multiple pods, it may already have been copied
                if not os.path.exists(destination_config_dir):
                    copytree(source_config_dir, destination_config_dir)
        # Copy the script files for the pod, if any
        if pod_has_scripts(parsed_stack, pod):
            destination_script_dir = destination_pod_dir.joinpath("scripts")
            os.makedirs(destination_script_dir)
            script_paths = get_pod_script_paths(parsed_stack, pod)
            _copy_files_to_directory(script_paths, destination_script_dir)
        if parsed_spec.is_kubernetes_deployment():
            for configmap in parsed_spec.get_configmaps():
                source_config_dir = resolve_config_dir(parsed_stack, configmap)
                if os.path.exists(source_config_dir):
                    destination_config_dir = deployment_dir_path.joinpath("configmaps", configmap)
                    copytree(source_config_dir, destination_config_dir, dirs_exist_ok=True)
        else:
            # TODO: We should probably only do this if the volume is marked :ro.
            for volume_name, volume_path in parsed_spec.get_volumes().items():
                source_config_dir = resolve_config_dir(parsed_stack, volume_name)
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
