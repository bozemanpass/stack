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

"""Output streams, with the ordinary Unix contract.

Results -- what a command exists to print, and what a pipeline consumes -- go
to stdout, via output_main().  Everything else is diagnostic and goes to
stderr: the log_* functions, and output relayed from subprocesses
(output_subcmd()).  So `stack manage --dir d secrets show | ...` pipes values
and nothing else, and 2>/dev/null silences commentary and nothing else.

`--log-file` redirects the diagnostic stream to a file, and that file
additionally records the results, so it reads as a complete session record
rather than one with holes where the output was; errors are still echoed to
stderr so a failure is not silent.  Results still go to stdout -- a pipeline
downstream of a logged run keeps working.

Decoration is a property of the destination, decided per write: color and
progress bars only when the stream being written is an interactive terminal,
never into a pipe or a file.
"""

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

    def log(self, msg, file, end=None):
        prefix = ""
        if opts.o.log_timestamps:
            prefix = f"{datetime.datetime.utcnow()}"
        if opts.o.log_elapsed:
            now = datetime.datetime.now()
            if prefix:
                prefix += " - "
            prefix += f"{now - self.last} (step) - {now - self.start} (total)"
            self.last = now
        if prefix:
            msg = f"{prefix}: {msg}"
        print(msg, file=file, end=end)
        if file:
            file.flush()


_logger = _TimedLogger()


def _stream_is_tty(stream):
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


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
    """True when the diagnostic stream is an interactive terminal.

    The condition for decoration beyond color -- progress bars and the like --
    which belongs on a screen a person is watching and in no pipe or file.
    """
    return _stream_is_tty(get_log_file())


def get_log_color(level: int):
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
    if not is_level_enabled(level):
        return
    output = get_log_file()
    if _stream_is_tty(output):
        if color is None:
            color = get_log_color(level)
        if color or bold:
            message = colored(message, color or None, attrs=["reverse", "bold"] if bold else None)
    _logger.log(message, file=output)


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
    # With the diagnostics diverted to a log file, an error must still reach the
    # terminal: a command that fails silently and leaves the reason in a file
    # nobody is watching is worse than a noisy one.
    if opts.o.log_file:
        if _stream_is_tty(sys.stderr):
            message = colored(message, get_log_color(level), attrs=["reverse", "bold"] if bold else None)
        print(message, file=sys.stderr)


def output_main(message, console=sys.stdout, end=None, bold=False):
    """A command's results: stdout, and only stdout, exactly once."""
    if opts.o.log_file:
        # The named log file records the results too -- see the module note.
        _logger.log(message, file=opts.o.log_file, end=end)
    if bold and _stream_is_tty(console):
        message = colored(message, attrs=["reverse", "bold"])
    print(message, end=end, file=console)


def output_subcmd(message, console=sys.stderr, end=None, bold=False):
    """Output relayed from a subprocess: diagnostic, so stderr or the log file."""
    if opts.o.log_file:
        _logger.log(message, file=opts.o.log_file, end=end)
        return
    if _stream_is_tty(console):
        message = colored(message, "magenta", attrs=["reverse", "bold"] if bold else None)
    _logger.log(message, end=end, file=console)
