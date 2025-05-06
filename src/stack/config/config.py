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

from stack.deploy.deploy import create_deploy_context
from stack.deploy.deployment_create import init_operation
from stack.util import check_if_stack_exists, global_options2, error_exit


@click.group()
@click.option("--env-file", help="env file to be used")
@click.option("--cluster", help="specify a non-default cluster name")
@click.option("--deploy-to", help="cluster system to deploy to (compose or k8s or k8s-kind)")
@click.pass_context
def command(ctx, env_file, cluster, deploy_to):
    """make configuration files for deploying a stack"""

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
        env_file,
        deploy_to,
    )
    # Subcommand is executed now, by the magic of click


@click.command()
@click.option("--stack", help="path to the stack", required=True)
@click.option("--config", help="Provide config variables for the deployment", multiple=True)
@click.option("--config-file", help="Provide config variables in a file for the deployment")
@click.option("--kube-config", help="Provide a config file for a k8s deployment")
@click.option(
    "--image-registry",
    help="Provide a container image registry url for this k8s cluster",
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
def init(
    ctx,
    stack,
    config,
    config_file,
    kube_config,
    image_registry,
    http_proxy,
    output,
    map_ports_to_host,
):
    """output a stack specification file"""
    check_if_stack_exists(stack)

    config_variables = {}
    for c in config:
        if "=" in c:
            k, v = c.split("=", 1)
            config_variables[k] = v.strip("'").strip('"')
        else:
            error_exit(f"Invalid config variable: {c}")

    deployer_type = ctx.obj.deployer.type
    deploy_command_context = ctx.obj
    deploy_command_context.stack = stack
    return init_operation(
        deploy_command_context,
        stack,
        deployer_type,
        config_variables,
        config_file,
        kube_config,
        image_registry,
        http_proxy,
        output,
        map_ports_to_host,
    )


command.add_command(init)
