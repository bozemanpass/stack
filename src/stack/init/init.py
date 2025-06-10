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

from stack.config.util import get_config_setting
from stack.deploy.deploy import create_deploy_context
from stack.deploy.deployment_create import init_operation
from stack.deploy.stack import get_parsed_stack_config
from stack.util import check_if_stack_exists, global_options2, error_exit, get_yaml


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
    "--http-proxy",
    required=False,
    help="k8s http proxy settings in the form: [cluster-issuer~]<host>[/path]:<target_svc>:<target_port>",
    multiple=True,
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
    http_proxy,
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
    check_if_stack_exists(stack)

    stack_config = get_parsed_stack_config(stack)
    required_stacks = stack_config.get_required_stacks_paths()
    config_variables = {}
    for c in config:
        if "=" in c:
            k, v = c.split("=", 1)
            config_variables[k] = v.strip("'").strip('"')
        else:
            error_exit(f"Invalid config variable: {c}")

    specs = []
    for i, stack in enumerate(required_stacks):
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
            http_proxy if i == len(required_stacks) - 1 else None,
            None,
            map_ports_to_host,
        )
        specs.append(spec)

    if len(specs) == 1:
        specs[0].dump(output)
    else:
        get_yaml().dump([spec.obj for spec in specs], open(output, "w"))
