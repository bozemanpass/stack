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

from stack.util import get_yaml
from stack.deploy.deploy_types import DeployCommandContext
from stack.deploy.deployment_context import DeploymentContext
from stack.deploy.spec import Spec
from stack.deploy.stack import Stack

default_spec_file_content = """config:
    test-variable-1: test-value-1
"""


def init(deploy_cmd_ctx: DeployCommandContext, spec: Spec):
    yaml = get_yaml()
    spec.obj.update(yaml.load(default_spec_file_content))
    return spec


def create(deploy_cmd_ctx: DeployCommandContext, deployment_ctx: DeploymentContext, stack: Stack):
    data = "create-command-output-data"
    output_file_path = deployment_ctx.deployment_dir.joinpath("create-file")
    with open(output_file_path, "w+") as output_file:
        output_file.write(data)
