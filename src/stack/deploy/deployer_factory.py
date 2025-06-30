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

from stack import constants
from stack.deploy.k8s.deploy_k8s import K8sDeployer, K8sDeployerConfigGenerator
from stack.deploy.compose.deploy_docker import (
    DockerDeployer,
    DockerDeployerConfigGenerator,
)
from stack.util import error_exit


def getDeployerConfigGenerator(type: str, deployment_context):
    if type == "compose" or type is None:
        return DockerDeployerConfigGenerator("compose", deployment_context)
    elif type == constants.k8s_deploy_type or type == constants.k8s_kind_deploy_type:
        return K8sDeployerConfigGenerator(type, deployment_context)
    else:
        error_exit(f"deploy-to {type} is not valid")


def getDeployer(type: str, deployment_context, compose_files, compose_project_name, compose_env_file):
    if type == "compose" or type is None:
        return DockerDeployer(
            "compose",
            deployment_context,
            compose_files,
            compose_project_name,
            compose_env_file,
        )
    elif type == type == constants.k8s_deploy_type or type == constants.k8s_kind_deploy_type:
        return K8sDeployer(
            type,
            deployment_context,
            compose_files,
            compose_project_name,
            compose_env_file,
        )
    else:
        error_exit(f"deploy-to {type} is not valid")
