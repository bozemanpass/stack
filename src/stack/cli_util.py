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
import os
import string
import sys
import importlib.util

from click import Context, HelpFormatter
from gettext import gettext as _

from stack.deploy.stack import resolve_stack


class StackCLI(click.Group):
    command_group_section_name = {}

    def add_command_group_section(self, name: str):
        self.command_group_section_name[name] = name

    def format_commands(self, ctx: Context, formatter: HelpFormatter) -> None:
        command_sections = {"core": []}

        for sub in self.command_group_section_name:
            command_sections[sub] = []

        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None or cmd.hidden:
                continue

            section_name = "core"
            if "-" in subcommand and subcommand.split("-")[0] in self.command_group_section_name:
                section_name = subcommand.split("-")[0]
            command_sections[section_name].append((subcommand, cmd))

        for section_name, commands in command_sections.items():
            if len(commands):
                limit = formatter.width - 6 - max(len(cmd[0]) for cmd in commands)

                rows = []
                for subcommand, cmd in commands:
                    help = cmd.get_short_help_str(limit)
                    rows.append((subcommand, help))

                if rows:
                    with formatter.section(section_name.capitalize() + " " + _("Commands")):
                        formatter.write_dl(rows)


def load_subcommands_from_stack(cli, stack_path: str):
    stack = resolve_stack(stack_path)
    cmds_path = stack.file_path.parent.joinpath("subcommands")
    if os.path.exists(cmds_path):
        p = 0
        for filename in os.listdir(cmds_path):
            if filename.endswith(".py") and filename != "__init__.py":
                full_path = os.path.join(cmds_path, filename)
                module_name = f"stack.plugin.{p}"
                spec = importlib.util.spec_from_file_location(module_name, full_path)
                plugin_module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = plugin_module
                spec.loader.exec_module(plugin_module)
                if hasattr(plugin_module, "command"):
                    cmd_section = make_safe_name(stack.name)
                    cmd_name = make_safe_name(filename[:-3])
                    if hasattr(plugin_module, "STACK_CLI_CMD_NAME"):
                        cmd_name = plugin_module.STACK_CLI_CMD_NAME
                    if hasattr(plugin_module, "STACK_CLI_CMD_SECTION"):
                        cmd_section = plugin_module.STACK_CLI_CMD_SECTION
                    cli.add_command_group_section(cmd_section)
                    cli.add_command(plugin_module.command, f"{cmd_section}-{cmd_name}")


def make_safe_name(v: str):
    if not v:
        return None
    # all punctuation removed except for - and _, whitespace replaced by -, letters converted to lower case
    return "-".join(v.translate(str.maketrans("", "", string.punctuation.replace("-", "").replace("_", ""))).split()).lower()
