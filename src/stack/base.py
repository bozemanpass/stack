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

import os

from abc import ABC, abstractmethod
from stack.config.util import get_config_setting
from stack.deploy.deploy import get_stack_status
from stack.log import log_error, log_debug


def get_stack(config, stack):
    if stack == "package-registry":
        return package_registry_stack(config, stack)
    else:
        return base_stack(config, stack)


class base_stack(ABC):
    def __init__(self, config, stack):
        self.config = config
        self.stack = stack

    @abstractmethod
    def ensure_available(self):
        pass

    @abstractmethod
    def get_url(self):
        pass


class package_registry_stack(base_stack):
    def ensure_available(self):
        self.url = "<no registry url set>"
        # Check if we were given an external registry URL
        url_from_environment = os.environ.get("STACK_NPM_REGISTRY_URL")
        if url_from_environment:
            log_debug(f"Using package registry url from STACK_NPM_REGISTRY_URL: {url_from_environment}")
            self.url = url_from_environment
        else:
            # Otherwise we expect to use the local package-registry stack
            # First check if the stack is up
            registry_running = get_stack_status(self.config, "package-registry")
            if registry_running:
                # If it is available, get its mapped port and construct its URL
                log_debug("Found local package registry stack is up")
                # TODO: get url from deploy-stack
                self.url = "http://gitea.local:3000/api/packages/bozemanpass/npm/"
            else:
                # If not, print a message about how to start it and return fail to the caller
                log_error(
                    "ERROR: The package-registry stack is not running, and no external registry "
                    "specified with STACK_NPM_REGISTRY_URL"
                )
                log_error("ERROR: Start the local package registry with: stack --stack package-registry deploy up")
                return False
        return True

    def get_url(self):
        return self.url


def get_npm_registry_url():
    return get_config_setting("STACK_NPM_REGISTRY_URL", default="")
