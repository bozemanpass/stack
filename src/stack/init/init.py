# Copyright © 2025 Bozeman Pass, Inc.
import socket

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

from stack import constants
from stack.config.util import get_config_setting
from stack.deploy.deploy import create_deploy_context
from stack.deploy.deployment_create import init_operation
from stack.deploy.spec import MergedSpec
from stack.deploy.stack import get_parsed_stack_config, determine_fs_path_for_stack, resolve_stack
from stack.util import global_options2, error_exit, get_yaml


def _parse_http_proxy(raw_val: str):
    stripped = raw_val.replace("http://", "").replace("https://", "")
    parts = stripped.split(":")
    if len(parts) == 2:
        service, port = parts
        path = "/"
    elif len(parts) == 3:
        path, service, port = parts
    else:
        error_exit(f"Invalid http-proxy target: {raw_val}")

    return {"service": service, "port": port, "path": path}


def _output_checks(specs, deploy_to):
    merged = MergedSpec()
    for spec in specs:
        merged.merge(spec)

    if deploy_to in [constants.k8s_kind_deploy_type, constants.k8s_deploy_type]:
        if not merged.get_http_proxy():
            print("WARN: Not HTTP proxy settings specified, no external HTTP access will be configured.")
        else:
            known_targets = set()
            for svc, ports in merged.get_network_ports().items():
                for port in ports:
                    known_targets.add(f"{svc}:{port}")

            paths = set()
            for proxy in merged.get_http_proxy():
                for route in proxy[constants.routes_key]:
                    if route[constants.proxy_to_key] not in known_targets:
                        print(
                            f"WARN: Unable to match http-proxy target {route[constants.proxy_to_key]} "
                            f"to a ClusterIP service and port."
                        )
                    if route[constants.path_key] in paths:
                        error_exit(f"Duplicate http-proxy path in {merged.get_http_proxy()}")
                    else:
                        paths.add(route[constants.path_key])


@click.command()
@click.option("--stack", help="path to the stack", required=False)
@click.option("--config", help="Provide config variables for the deployment", multiple=True)
@click.option("--config-file", help="Provide config variables in a file for the deployment")
@click.option("--cluster", help="specify a non-default cluster name")
@click.option(
    "--deploy-to",
    help="cluster system to deploy to (compose or k8s or k8s-kind)",
    default=get_config_setting("deploy-to", "compose"),
)
@click.option("--kube-config", help="Provide a config file for a k8s deployment", default=get_config_setting("kube-config"))
@click.option(
    "--image-registry",
    help="Provide a container image registry url for this k8s cluster",
    default=get_config_setting("image-registry"),
)
@click.option(
    "--http-proxy-target",
    required=False,
    help="k8s http proxy settings in the form: target_svc:target_port[path]]",
    multiple=True,
)
@click.option(
    "--http-proxy-fqdn",
    required=False,
    help="k8s http proxy hostname to use",
    default=get_config_setting("http-proxy-fqdn", socket.getfqdn()),
)
@click.option(
    "--http-proxy-clusterissuer",
    required=False,
    help="k8s http proxy hostname to use",
    default=get_config_setting("http-proxy-clusterissuer", "letsencrypt-prod"),
)
@click.option("--output", required=True, help="Write yaml spec file here")
@click.option(
    "--map-ports-to-host",
    required=False,
    help="Map ports to the host as one of: any-variable-random (docker default), "
    "localhost-same, any-same, localhost-fixed-random, any-fixed-random, "
    "k8s-clusterip-same (k8s default)",
)
@click.pass_context
def command(
    ctx,
    stack,
    deploy_to,
    cluster,
    config,
    config_file,
    kube_config,
    image_registry,
    http_proxy_fqdn,
    http_proxy_clusterissuer,
    http_proxy_target,
    output,
    map_ports_to_host,
):
    """create a stack specification file"""
    if ctx.parent.obj.debug:
        print(f"ctx.parent.obj: {ctx.parent.obj}")

    if deploy_to is None:
        deploy_to = "compose"

    ctx.obj = create_deploy_context(
        global_options2(ctx),
        None,
        None,
        None,
        None,
        cluster,
        config_file,
        deploy_to,
    )

    if not stack:
        stack = ctx.obj.stack_path

    top_stack_config = resolve_stack(stack)
    required_stacks = top_stack_config.get_required_stacks_paths()
    config_variables = {}
    for c in config:
        if "=" in c:
            k, v = c.split("=", 1)
            config_variables[k] = v.strip("'").strip('"')
        else:
            error_exit(f"Invalid config variable: {c}")

    def http_prefix_for(stack):
        stacks = top_stack_config.get_required_stacks()
        for s in stacks:
            stack_path = determine_fs_path_for_stack(s[constants.ref_key], s[constants.path_key])
            if stack_path == stack:
                return s.get(constants.http_proxy_prefix_key, None)
        return None

    if http_proxy_target:
        if deploy_to not in [constants.k8s_kind_deploy_type, constants.k8s_deploy_type]:
            error_exit(f"--http-proxy-target is not allowed with a {deploy_to} deployment")
        http_proxy_target = [_parse_http_proxy(t) for t in http_proxy_target]

    specs = []
    warned_about_http_prefix = False
    for i, stack in enumerate(required_stacks):
        http_prefix = None
        if top_stack_config.is_super_stack():
            http_prefix = http_prefix_for(stack)
        if http_prefix:
            if not warned_about_http_prefix and deploy_to not in [constants.k8s_kind_deploy_type, constants.k8s_deploy_type]:
                print(f"NOTE: {constants.http_proxy_prefix_key} setting is only used when deploying to Kubernetes.")
                warned_about_http_prefix = True

        inner_stack_config = get_parsed_stack_config(stack)
        http_proxy_targets = inner_stack_config.get_http_proxy_targets(http_prefix)

        if i == len(required_stacks) - 1:
            http_proxy_targets.extend(http_proxy_target)

        deployer_type = ctx.obj.deployer.type
        deploy_command_context = ctx.obj
        deploy_command_context.stack = stack
        spec = init_operation(
            deploy_command_context,
            str(stack),
            deployer_type,
            config_variables,
            config_file,
            kube_config,
            image_registry,
            http_proxy_fqdn,
            http_proxy_clusterissuer,
            http_proxy_targets,
            None,
            map_ports_to_host,
        )
        specs.append(spec)

    _output_checks(specs, deploy_to)

    if len(specs) == 1:
        specs[0].dump(output)
    else:
        get_yaml().dump([spec.obj for spec in specs], open(output, "w"))
