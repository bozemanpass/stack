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
from pathlib import Path

from stack.util import get_yaml, is_primitive


def get_config_dir():
    return Path(os.path.expanduser("~/.stack"))


def get_config_file_path():
    return get_config_dir().joinpath(os.environ.get("STACK_CONFIG_PROFILE", "config") + ".yml")


def get_config():
    config_path = get_config_file_path()
    if config_path.exists():
        yaml = get_yaml()
        return yaml.load(open(config_path, "r"))

    return {}


def save_config(config):
    config_dir = get_config_dir()
    if not config_dir.exists():
        config_dir.mkdir(parents=True)

    yaml = get_yaml()
    yaml.dump(config, open(config_dir, "w+"))


def get_config_setting(key, default=None):
    config = get_config()

    parts = key.split(".")
    if len(parts) == 1:
        return config.get(key, default)

    for i in range(len(parts)):
        part = parts[i]
        if i == len(parts) - 1:
            return config.get(part, default)
        else:
            config = config.get(part, {})
            if is_primitive(config):
                return default

    return default
