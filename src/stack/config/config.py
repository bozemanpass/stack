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
from stack.util import get_yaml, is_primitive


@click.group()
@click.pass_context
def command(ctx):
    """manage configuration settings for the stack command"""

    if ctx.parent.obj.debug:
        print(f"ctx.parent.obj: {ctx.parent.obj}")

    # Subcommand is executed now, by the magic of click


@click.command()
@click.pass_context
def show(ctx):
    """show the full configuration"""
    config = get_config()
    yaml = get_yaml()
    click.echo(yaml.dumps(config))


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
            click.echo(str(value).lower())
        else:
            click.echo(value)
    else:
        click.echo(get_yaml().dumps(value))


@click.command()
@click.argument("key", required=True)
@click.argument("value", required=True)
@click.pass_context
def set(ctx, key, value):
    """set the value of a configuration setting"""
    config = get_config()
    parts = key.split(".")

    try:
        value = json.loads(value)
    except:  # noqa: E722
        pass

    if len(parts) == 1:
        config[key] = value
        save_config(config)
        return

    section = config
    for i in range(len(parts)):
        part = parts[i]
        if i == len(parts) - 1:
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


command.add_command(get)
command.add_command(set)
command.add_command(show)
