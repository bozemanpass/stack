# Copyright © 2024 Vulcanize

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


from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from stack.deploy.stack import Stack
from stack.build.build_util import ContainerSpec


@dataclass
class BuildContext:
    stack: Stack
    container: ContainerSpec
    default_container_base_dir: Path
    container_build_env: Mapping[str,str]
    dev_root_path: Path

