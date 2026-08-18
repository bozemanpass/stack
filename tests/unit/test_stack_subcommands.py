# Copyright © 2026 Bozeman Pass, Inc.

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

"""Tests for stack-contributed subcommands (docs/subcommands.md): a `subcommands`
directory next to a stack.yml adds `<stack>-<file>` commands to the CLI.

The registration used to be triggered by scanning sys.argv for `--stack`, which
stopped working the moment that option moved off the CLI group (issue #233) --
with nothing in CI to notice.  These tests invoke a subcommand for real, so a
future change to the trigger fails here rather than in a user's terminal."""

import textwrap

from conftest import make_stack_fixture, run_stack


HELLO_COMMAND = """\
    import click

    @click.command()
    @click.pass_context
    def command(ctx):
        \"\"\"hello description here\"\"\"

        print("Hello")
    """


def make_stack_with_subcommand(tmp_path, source=HELLO_COMMAND, name="example", filename="hello.py"):
    """A stack beneath a repo base dir of its own, carrying one subcommand file."""
    repo_base = tmp_path / "repos"
    repo_base.mkdir()
    stack_dir = make_stack_fixture(repo_base, name=name)
    subcommands_dir = stack_dir / "subcommands"
    subcommands_dir.mkdir()
    (subcommands_dir / filename).write_text(textwrap.dedent(source))
    return repo_base


def env_for(isolated_env, repo_base):
    return {**isolated_env, "STACK_REPO_BASE_DIR": str(repo_base)}


def test_subcommand_can_be_invoked_by_name(tmp_path, isolated_env):
    repo_base = make_stack_with_subcommand(tmp_path)
    result = run_stack(["example-hello"], env_for(isolated_env, repo_base))
    assert result.returncode == 0, result.stderr
    assert "Hello" in result.stdout


def test_subcommand_is_listed_in_help_under_the_stack_name(tmp_path, isolated_env):
    repo_base = make_stack_with_subcommand(tmp_path)
    result = run_stack(["-h"], env_for(isolated_env, repo_base))
    assert result.returncode == 0, result.stderr
    assert "Example Commands:" in result.stdout
    assert "example-hello" in result.stdout
    assert "hello description here" in result.stdout


def test_subcommand_name_can_be_overridden_by_the_command_file(tmp_path, isolated_env):
    source = textwrap.dedent(HELLO_COMMAND) + '\nSTACK_CLI_CMD_NAME = "greet"\nSTACK_CLI_CMD_SECTION = "demo"\n'
    repo_base = make_stack_with_subcommand(tmp_path, source=source)
    result = run_stack(["demo-greet"], env_for(isolated_env, repo_base))
    assert result.returncode == 0, result.stderr
    assert "Hello" in result.stdout


def test_a_broken_subcommand_file_does_not_break_the_cli(tmp_path, isolated_env):
    """The loader runs arbitrary code from a stack, so it must be able to fail
    without taking every other command down with it."""
    repo_base = make_stack_with_subcommand(tmp_path, source="raise RuntimeError('boom')\n")
    result = run_stack(["version"], env_for(isolated_env, repo_base))
    assert result.returncode == 0, result.stderr

    result = run_stack(["-h"], env_for(isolated_env, repo_base))
    assert result.returncode == 0, result.stderr
    assert "boom" in result.stderr
    assert "example-hello" not in result.stdout


def test_unknown_command_still_reports_no_such_command(tmp_path, isolated_env):
    repo_base = make_stack_with_subcommand(tmp_path)
    result = run_stack(["example-nosuch"], env_for(isolated_env, repo_base))
    assert result.returncode != 0
    assert "No such command" in result.stderr
