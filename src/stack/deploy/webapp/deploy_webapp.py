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
from pathlib import Path
from urllib.parse import urlparse
from tempfile import NamedTemporaryFile

from stack import constants
from stack.util import error_exit, global_options2
from stack.deploy.deployment_create import init_operation, create_operation
from stack.deploy.deploy import create_deploy_context
from stack.deploy.deploy_types import DeployCommandContext
from stack.deploy.spec import Spec


def _fixup_container_tag(deployment_dir: str, image: str):
    deployment_dir_path = Path(deployment_dir)
    compose_file = deployment_dir_path.joinpath("compose", f"{constants.compose_file_prefix}-webapp-template.yml")
    # replace "bpi/webapp-container:stack" in the file with our image tag
    with open(compose_file) as rfile:
        contents = rfile.read()
        contents = contents.replace("bpi/webapp-container:stack", image)
    with open(compose_file, "w") as wfile:
        wfile.write(contents)


def _fixup_url_spec(spec_file_name: str, url: str):
    # url is like: https://example.com/path
    parsed_url = urlparse(url)
    http_proxy_spec = f"""
  http-proxy:
    - host-name: {parsed_url.hostname}
      routes:
        - path: '{parsed_url.path if parsed_url.path else "/"}'
          proxy-to: webapp:80
    """
    spec_file_path = Path(spec_file_name)
    with open(spec_file_path) as rfile:
        contents = rfile.read()
        contents = contents + http_proxy_spec
    with open(spec_file_path, "w") as wfile:
        wfile.write(contents)


def create_deployment(ctx, deployment_dir, image, url, kube_config, image_registry, env_file):
    # Do the equivalent of:
    # 1. stack --stack webapp-template deploy --deploy-to k8s init --output webapp-spec.yml
    #   --config (eqivalent of the contents of my-config.env)
    # 2. stack  --stack webapp-template deploy --deploy-to k8s create --deployment-dir test-deployment
    #   --spec-file webapp-spec.yml
    # 3. Replace the container image tag with the specified image
    deployment_dir_path = Path(deployment_dir)
    # Check the deployment dir does not exist
    if deployment_dir_path.exists():
        error_exit(f"Deployment dir {deployment_dir} already exists")
    # Generate a temporary file name for the spec file
    tf = NamedTemporaryFile(prefix="webapp-", suffix=".yml", delete=False)
    spec_file_name = tf.name
    # Specify the webapp template stack
    stack = "webapp-template"

    deployment_type = "compose"
    if kube_config:
        deployment_type = "k8s"

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
        None,
        None,
        None,
        spec_file_name,
        None,
    )
    # Add the TLS and DNS spec
    _fixup_url_spec(spec_file_name, url)
    spec = Spec().init_from_file(spec_file_name)
    create_operation(deploy_command_context, spec, deployment_dir)
    # Fix up the container tag inside the deployment compose file
    _fixup_container_tag(deployment_dir, image)
    os.remove(spec_file_name)


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
        print("WARN: --image-registry not specified, only default container registries (eg, Docker Hub) will be available")

    return create_deployment(ctx, deployment_dir, image, url, kube_config, image_registry, config_file)
