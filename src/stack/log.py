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

import datetime
import sys

from termcolor import colored
from stack.opts import opts


LOG_LEVELS = {
    "debug": 20,
    "info": 30,
    "warn": 40,
    "error": 50,
}


class _TimedLogger:
    def __init__(self):
        self.start = datetime.datetime.now()
        self.last = self.start

    def log(self, msg, file, end=None, show_step_time=False, show_total_time=False):
        prefix = f"{datetime.datetime.utcnow()}"
        if show_step_time:
            prefix += f" - {datetime.datetime.now() - self.last} (step)"
        if show_total_time:
            prefix += f" - {datetime.datetime.now() - self.start} (total)"
        print(f"{prefix}: {msg}", file=file, end=end)
        if file:
            file.flush()
        self.last = datetime.datetime.now()


_logger = _TimedLogger()


def is_debug_enabled():
    return is_level_enabled(LOG_LEVELS["debug"])


def is_info_enabled():
    return is_level_enabled(LOG_LEVELS["info"])


def is_warn_enabled():
    return is_level_enabled(LOG_LEVELS["warn"])


def is_level_enabled(level):
    return opts.o.log_level <= level


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


def raw_log(message, level, color=None, bold=False):
    if is_level_enabled(level):
        output = get_log_file()
        if not log_is_console():
            _logger.log(f"{message}", file=output)
        else:
            if color is None:
                color = get_log_color(level)
            if color:
                message = colored(message, color, attrs=["reverse", "bold"] if bold else None)
            elif bold:
                message = colored(message, attrs=["reverse", "bold"] if bold else None)
            _logger.log(f"{message}", file=output)


def log_debug(message, bold=False):
    level = LOG_LEVELS["debug"]
    raw_log(message, level, bold=bold)


def log_info(message, bold=False):
    level = LOG_LEVELS["info"]
    raw_log(message, level, bold=bold)


def log_warn(message, bold=False):
    level = LOG_LEVELS["warn"]
    raw_log(message, level, bold=bold)


def log_error(message, bold=False):
    level = LOG_LEVELS["error"]
    raw_log(message, level, bold=bold)
    if not log_is_console():
        print(colored(message, get_log_color(level), attrs=["reverse", "bold"] if bold else None), file=sys.stderr)


def output_main(message, console=sys.stdout, end=None, bold=False):
    if not log_is_console():
        _logger.log(message, file=get_log_file(), end=end)
    print(colored(message, attrs=["reverse", "bold"] if bold else None), end=end, file=console)


def output_subcmd(message, console=sys.stderr, end=None, bold=False):
    if log_is_console():
        _logger.log(colored(message, "magenta", attrs=["reverse", "bold"] if bold else None), end=end, file=console)

    if not log_is_console():
        _logger.log(message, file=get_log_file(), end=end)
