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
import json

from stack.config.util import get_config, save_config, get_config_setting
from stack.log import output_main
from stack.util import get_yaml, is_primitive


def set_config_value(key, value):
    config = get_config()
    parts = key.split(".")

    try:
        value = json.loads(value)
    except:  # noqa: E722
        pass

    if len(parts) == 1:
        if value is None:
            config.pop(key, None)
        else:
            config[key] = value
        save_config(config)
        return

    section = config
    for i in range(len(parts)):
        part = parts[i]
        if i == len(parts) - 1:
            if value is None:
                config.pop(key, None)
            else:
                section[part] = value
        else:
            if part not in section:
                section[part] = {}
            prev = section
            section = section[part]
            if not isinstance(section, dict):
                section = {}
                prev[part] = section

    save_config(config)


@click.group()
@click.pass_context
def command(ctx):
    """manage configuration settings for the stack command"""

    # Subcommand is executed now, by the magic of click
    pass


@click.command()
@click.pass_context
def show(ctx):
    """show the full configuration"""
    config = get_config()
    yaml = get_yaml()
    if config:
        output_main(yaml.dumps(config))


@click.command()
@click.argument("key", required=True)
@click.pass_context
def get(ctx, key):
    """get the value of a configuration setting"""

    value = get_config_setting(key)
    if value is None:
        return

    if is_primitive(value):
        if isinstance(value, bool):
            output_main(str(value).lower())
        else:
            output_main(value)
    else:
        output_main(get_yaml().dumps(value))


@click.command()
@click.argument("key", required=True)
@click.argument("value", required=False)
@click.pass_context
def set(ctx, key, value):
    """set the value of a configuration setting"""

    set_config_value(key, value)


@click.command()
@click.argument("key", required=True)
@click.pass_context
def unset(ctx, key):
    """remove a configuration setting"""

    set_config_value(key, None)


command.add_command(get)
command.add_command(set)
command.add_command(unset)
command.add_command(show)
