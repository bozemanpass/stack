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
from pygments.lexers import shell

from stack.log import output_main
from stack.util import error_exit


# EXPERIMENTAL

SHELL_COMPLETIONS = {
    "bash": r"""
_stack_completions()
{
  if [ "${#COMP_WORDS[@]}" == "2" ]; then
    COMPREPLY=($(compgen -W "$(stack -h | grep -A99 '^Core Commands' | tail +2 | awk '{print $1}')" -- "${COMP_WORDS[1]}"))
    return
  fi

  local lix=$((${#COMP_WORDS[@]} - 1))
  if [ "${COMP_WORDS[$((lix-1))]}" == "--stack" ]; then
    COMPREPLY=($(compgen -W "$(stack list)" -- "${COMP_WORDS[$((lix))]}"))
    return
  fi

  if [ ${#COMP_WORDS[@]} -gt 2 ]; then
    if [[ ${COMP_WORDS[$((lix))]} = --* ]]; then
      SHORTER="${COMP_WORDS[@]::${#COMP_WORDS[@]}-1}"
      TRY=$(bash -c "$SHORTER --help")
      if [ $? -eq 0 ] && [ -n "$TRY" ]; then
        COMPREPLY=($(compgen -W "$(bash -c "$SHORTER --help" | grep '\--' | grep -v '\--help' | awk '{ print $1 }')" -- "${COMP_WORDS[$((lix))]}"))
      fi
    elif [[ -z ${COMP_WORDS[$((lix))]} ]]; then
      TRY=$(${COMP_WORDS[*]} --help 2>/dev/null)
      if [ $? -eq 0 ] && [ -n "$TRY" ]; then
        COMPREPLY=($(compgen -W "$(${COMP_WORDS[*]} --help 2>/dev/null | grep -A99 'Commands' | tail +2 | awk '{ print $1 }')"))
      fi
    else
      TRY=$(${COMP_WORDS[@]::${#COMP_WORDS[@]}-1} --help 2>/dev/null)
      if [ $? -eq 0 ] && [ -n "$TRY" ]; then
        COMPREPLY=($(compgen -W "$(${COMP_WORDS[@]::${#COMP_WORDS[@]}-1} --help 2>/dev/null | grep -A99 'Commands' | tail +2 | awk '{ print $1 }')" -- "${COMP_WORDS[$((lix))]}"))
      fi
    fi
    return
  fi

  COMPREPLY=()
}
complete -o bashdefault -o default -F _stack_completions stack
"""
}


@click.command(hidden=True)
@click.option("--shell", help="name of shell", default="bash")
@click.pass_context
def command(ctx, shell):
    """output shell completion script"""

    script = SHELL_COMPLETIONS.get(shell)
    if not script:
        error_exit(f"{shell} is not among supported shells: {SHELL_COMPLETIONS.keys()}")
    output_main(script)
