# Copyright © 2025 Bozeman Pass, Inc.
import io
import sys

import colorama
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

from termcolor import colored

from stack.opts import opts


LOG_LEVELS = {
    "debug": 20,
    "info": 30,
    "warn": 40,
    "error": 50,
}


def get_log_file():
    if opts.o.log_file:
        return opts.o.log_file
    return sys.stderr


def log_is_console():
    return not opts.o.log_file or opts.o.log_file.isatty()


def get_log_color(level: int):
    if not log_is_console():
        return ""

    if level == LOG_LEVELS["debug"]:
        return "blue"
    elif level == LOG_LEVELS["info"]:
        return "green"
    elif level == LOG_LEVELS["warn"]:
        return "yellow"
    elif level == LOG_LEVELS["error"]:
        return "red"

    return ""


def raw_log(message, level):
    if level >= opts.o.log_level:
        output = get_log_file()
        color = get_log_color(level)
        if color :
            message = colored(message, color)
        print(f"{message}", file=output)


def log_debug(message):
    level = LOG_LEVELS["debug"]
    raw_log(message, level)


def log_info(message):
    level = LOG_LEVELS["info"]
    raw_log(message, level)


def log_warn(message):
    level = LOG_LEVELS["warn"]
    raw_log(message, level)


def log_error(message):
    level = LOG_LEVELS["error"]
    raw_log(message, level)


def output_main(message):
    if not log_is_console():
        print(
            message,
            file=get_log_file()
        )
    print(message)


def output_sub(message):
    if not log_is_console():
        print(
            message,
            file=get_log_file()
        )
    print(colored(message, "magenta"))


def log_colorize_console_for_subprocess():
    if log_is_console():
        print(colorama.Style.RESET_ALL, file=get_log_file(), end="")
        print(colorama.Fore.MAGENTA, file=get_log_file())


def log_reset_console_color():
    if log_is_console():
        print(colorama.Style.RESET_ALL, file=get_log_file(), end="")
