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

from typing import List, Mapping
from dataclasses import dataclass
from stack.command_types import CommandOptions
from stack.deploy.deployer import Deployer


@dataclass
class ClusterContext:
    options: CommandOptions  # TODO: this should be in its own object not stuffed in here
    cluster: str
    compose_files: List[str]
    pre_start_commands: List[str]
    post_start_commands: List[str]
    config: str
    env_file: str


@dataclass
class DeployCommandContext:
    stack: str
    cluster_context: ClusterContext
    deployer: Deployer


@dataclass
class VolumeMapping:
    host_path: str
    container_path: str


@dataclass
class DeployEnvVars:
    map: Mapping[str, str]
