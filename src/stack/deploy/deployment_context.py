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

import glob
from pathlib import Path

from stack import constants
from stack.util import get_yaml, error_exit
from stack.deploy.spec import Spec


class DeploymentContext:
    deployment_dir: Path
    id: str
    spec: Spec

    def get_spec_file(self):
        return self.deployment_dir.joinpath(constants.spec_file_name)

    def get_env_file(self):
        return self.deployment_dir.joinpath(constants.config_file_name)

    def get_deployment_file(self):
        return self.deployment_dir.joinpath(constants.deployment_file_name)

    def get_compose_dir(self):
        return self.deployment_dir.joinpath(constants.compose_dir_name)

    def get_compose_files(self):
        return glob.glob(f"{self.get_compose_dir()}/{constants.compose_file_prefix}-*.yml")

    def get_cluster_id(self):
        return self.id

    def init(self, dir):
        self.deployment_dir = dir
        self.spec = Spec()
        self.spec.init_from_file(self.get_spec_file())
        deployment_file_path = self.get_deployment_file()
        if deployment_file_path.exists():
            with deployment_file_path:
                obj = get_yaml().load(open(deployment_file_path, "r"))
                self.id = obj[constants.cluster_id_key]
        else:
            error_exit(f"Missing {deployment_file_path}")
