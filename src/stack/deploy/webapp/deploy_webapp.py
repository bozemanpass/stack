# Copyright ©2023 Vulcanize
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
import shutil
from pathlib import Path
from urllib.parse import urlparse
from tempfile import NamedTemporaryFile, mkdtemp

from stack.util import error_exit, global_options2
from stack.deploy.deployment_create import init_operation, create_operation
from stack.deploy.deploy import create_deploy_context
from stack.deploy.deploy_types import DeployCommandContext
from stack.deploy.spec import Spec
from stack.log import log_warn

WEBAPP_PORT = 80


def _generate_stack(parent_dir: Path, image: str) -> Path:
    # Generate a single-pod stack serving the specified image.  The stack and compose
    # files are copied into the deployment during create, so the generated stack
    # itself can be discarded afterwards.
    stack_dir = parent_dir.joinpath("stack-files", "stacks", "webapp")
    compose_dir = parent_dir.joinpath("stack-files", "compose")
    os.makedirs(stack_dir)
    os.makedirs(compose_dir)

    with open(stack_dir.joinpath("stack.yml"), "w") as stack_file:
        stack_file.write(
            """version: "1.0"
name: webapp
description: "webapp deployment"
containers: []
pods:
  - webapp
"""
        )

    with open(compose_dir.joinpath("composefile-webapp.yml"), "w") as compose_file:
        compose_file.write(
            f"""services:
  webapp:
    image: {image}
    restart: always
    environment:
      STACK_SCRIPT_DEBUG: ${{STACK_SCRIPT_DEBUG}}
    ports:
      - "{WEBAPP_PORT}"
"""
        )

    return stack_dir


def create_deployment(ctx, deployment_dir, image, url, kube_config, image_registry, env_file):
    deployment_dir_path = Path(deployment_dir)
    # Check the deployment dir does not exist
    if deployment_dir_path.exists():
        error_exit(f"Deployment dir {deployment_dir} already exists")

    deployment_type = "compose"
    if kube_config:
        deployment_type = "k8s"

    http_proxy_fqdn = None
    http_proxy_targets = None
    if url:
        # url is like: https://example.com/path
        parsed_url = urlparse(url)
        http_proxy_fqdn = parsed_url.hostname
        http_proxy_targets = [
            {"path": parsed_url.path if parsed_url.path else "/", "service": "webapp", "port": WEBAPP_PORT}
        ]

    # Generate a temporary file name for the spec file
    tf = NamedTemporaryFile(prefix="webapp-", suffix=".yml", delete=False)
    spec_file_name = tf.name
    stack_parent_dir = mkdtemp(prefix="webapp-stack-")
    try:
        stack = str(_generate_stack(Path(stack_parent_dir), image))

        deploy_command_context: DeployCommandContext = create_deploy_context(
            global_options2(ctx),
            None,
            stack,
            None,
            None,
            None,
            env_file,
            deployment_type,
        )
        init_operation(
            deploy_command_context,
            stack,
            deployment_type,
            None,
            env_file,
            kube_config,
            image_registry,
            http_proxy_fqdn,
            None,
            http_proxy_targets,
            spec_file_name,
            None,
        )
        spec = Spec().init_from_file(spec_file_name)
        create_operation(deploy_command_context, spec, deployment_dir)
    finally:
        os.remove(spec_file_name)
        shutil.rmtree(stack_parent_dir)


@click.command()
@click.option("--kube-config", help="Provide a config file for a k8s deployment")
@click.option(
    "--image-registry",
    help="Provide a container image registry url (required for k8s)",
)
@click.option("--deployment-dir", help="Create deployment files in this directory", required=True)
@click.option("--image", help="image to deploy", required=True)
@click.option("--url", help="url to serve (required for k8s)", required=False)
@click.option("--config-file", help="environment file for webapp")
@click.pass_context
def create(ctx, deployment_dir, image, url, kube_config, image_registry, config_file):
    """create a deployment for the specified webapp container"""

    if kube_config and not url:
        error_exit("--url is required for k8s deployments")

    if kube_config and not image_registry:
        log_warn("WARN: --image-registry not specified, only default container registries (eg, Docker Hub) will be available")

    return create_deployment(ctx, deployment_dir, image, url, kube_config, image_registry, config_file)
