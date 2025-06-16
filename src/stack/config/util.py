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


_DEFAULTS = {"repo-base-dir": "~/.stack/repos"}


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
    config_path = get_config_file_path()
    if not config_path.parent.exists():
        config_path.parent.mkdir(parents=True)

    yaml = get_yaml()
    yaml.dump(config, open(config_path, "w+"))


def get_config_setting(key, default=None):
    key = key.lower().replace("_", "-")
    if key.startswith("stack-"):
        key = key[6:]

    # Check environment first
    ret = _get_from_env(key)

    # Next check file
    if ret is None:
        ret = _get_from_file(key)

    # Last check defaults
    if ret is None:
        # But only if we didn't get a default already
        if default is None:
            ret = _DEFAULTS.get(key, None)

    if ret is not None:
        # If it is a ~/ path, expand it.
        if str(ret).startswith("~/"):
            ret = os.path.expanduser(str(ret))
        # And parse a boolean if it is a string.
        if str(ret).lower() in ["true", "false"]:
            ret = str(ret).lower() == "true"

    if ret is None:
        return default

    return ret


def _get_from_env(key):
    key = key.upper().replace("-", "_")
    if not key.startswith("STACK_"):
        key = "STACK_" + key
    return os.environ.get(key, None)


def _get_from_file(key):
    config = get_config()

    parts = key.split(".")
    if len(parts) == 1:
        return config.get(key, None)

    for i in range(len(parts)):
        part = parts[i]
        if i == len(parts) - 1:
            return config.get(part, None)
        else:
            config = config.get(part, {})
            if is_primitive(config):
                return None

    return None


def get_dev_root_path():
    return get_config_setting("STACK_REPO_BASE_DIR")
