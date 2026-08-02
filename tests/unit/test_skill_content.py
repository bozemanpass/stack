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

# Tests for the agent skill(s) shipped in skills/.  The skill content itself is
# the test input: code blocks are extracted from SKILL.md and every `stack`
# invocation found there is validated against the real CLI's command tree, so
# editing the skill automatically changes what is tested, and a CLI change that
# invalidates the skill fails here rather than rotting silently.

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
PLUGIN_MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"

# Maximum length Claude Code accepts for a skill description.
MAX_DESCRIPTION_LENGTH = 1024

# Dumps the click command tree (options, flags, choices) as JSON.  Run in a
# subprocess because option defaults read the config profile at import time
# (see conftest.py), so the import must happen under an isolated HOME.
INTROSPECT_SCRIPT = """
import json
import click
from stack.main import cli

def dump(cmd):
    node = {"params": [], "subcommands": {}, "group": isinstance(cmd, click.Group)}
    for p in cmd.params:
        if isinstance(p, click.Option):
            node["params"].append({
                "opts": list(p.opts) + list(p.secondary_opts),
                "takes_value": not p.is_flag and not p.count,
                "choices": list(p.type.choices) if isinstance(p.type, click.Choice) else None,
            })
    if isinstance(cmd, click.Group):
        ctx = click.Context(cmd)
        for name in sorted(cmd.list_commands(ctx)):
            sub = cmd.get_command(ctx, name)
            if sub is not None:
                node["subcommands"][name] = dump(sub)
    return node

print(json.dumps(dump(cli)))
"""

SHELL_OPERATORS = ("|", "||", "&&", ";", ">", ">>", "<")


def skill_files():
    return sorted(SKILLS_DIR.glob("*/SKILL.md"))


def parse_skill(skill_path):
    """Split a SKILL.md into (frontmatter dict, body text)."""
    text = skill_path.read_text()
    assert text.startswith("---\n"), f"{skill_path}: missing frontmatter"
    end = text.index("\n---\n", 4)
    frontmatter = yaml.safe_load(text[4:end])
    return frontmatter, text[end + 5:]


def fenced_blocks(body):
    """Return (language, content) for each fenced code block."""
    blocks = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^\s*```(\w*)\s*$", lines[i])
        if m:
            lang, content = m.group(1), []
            i += 1
            while i < len(lines) and not re.match(r"^\s*```\s*$", lines[i]):
                content.append(lines[i])
                i += 1
            assert i < len(lines), "unterminated code fence"
            blocks.append((lang, "\n".join(content)))
        i += 1
    return blocks


def stack_invocations(skill_path):
    """Extract every `stack ...` command from the skill's shell code blocks."""
    _, body = parse_skill(skill_path)
    invocations = []
    for lang, content in fenced_blocks(body):
        if lang not in ("", "bash", "sh"):
            continue
        # Join backslash line continuations into logical lines
        logical, pending = [], ""
        for line in content.splitlines():
            line = pending + line
            pending = ""
            if line.rstrip().endswith("\\"):
                pending = line.rstrip()[:-1] + " "
            else:
                logical.append(line)
        if pending:
            logical.append(pending)
        for line in logical:
            try:
                tokens = shlex.split(line, comments=True)
            except ValueError:
                continue
            for op in SHELL_OPERATORS:
                if op in tokens:
                    tokens = tokens[: tokens.index(op)]
            if tokens and tokens[0] == "stack":
                invocations.append((line.strip(), tokens[1:]))
    return invocations


def validate_invocation(tokens, tree):
    """Walk an invocation's tokens against the introspected command tree."""
    node, path, i = tree, ["stack"], 0
    while i < len(tokens):
        t = tokens[i]
        if t in ("--help", "-h"):
            i += 1
            continue
        if t.startswith("-") and t != "-":
            name, _, inline_value = t.partition("=")
            param = next((p for p in node["params"] if name in p["opts"]), None)
            assert param is not None, f"`{' '.join(path)}` has no option `{name}`"
            value = None
            if param["takes_value"]:
                if inline_value:
                    value = inline_value
                else:
                    i += 1
                    assert i < len(tokens), f"option `{name}` is missing its value"
                    value = tokens[i]
            if param["choices"] and value is not None:
                assert value in param["choices"], (
                    f"`{value}` is not a valid choice for `{name}` " f"(choices: {param['choices']})"
                )
            i += 1
        elif t in node["subcommands"]:
            node = node["subcommands"][t]
            path.append(t)
            i += 1
        elif node["group"]:
            raise AssertionError(f"`{t}` is not a subcommand of `{' '.join(path)}`")
        else:
            # Positional arguments of a leaf command; not validated further
            break


@pytest.fixture(scope="module")
def cli_tree(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    env = {k: v for k, v in os.environ.items() if not k.startswith("STACK_")}
    env["HOME"] = str(home)
    result = subprocess.run(
        [sys.executable, "-c", INTROSPECT_SCRIPT],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"CLI introspection failed: {result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("skill_path", skill_files(), ids=lambda p: p.parent.name)
def test_skill_frontmatter(skill_path):
    frontmatter, _ = parse_skill(skill_path)
    assert frontmatter["name"] == skill_path.parent.name, "frontmatter name must match the skill directory name"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", frontmatter["name"]), "skill name must be kebab-case"
    description = frontmatter.get("description", "")
    assert description.strip(), "skill must have a description"
    assert len(description) <= MAX_DESCRIPTION_LENGTH


@pytest.mark.parametrize("skill_path", skill_files(), ids=lambda p: p.parent.name)
def test_skill_yaml_blocks_parse(skill_path):
    _, body = parse_skill(skill_path)
    yaml_blocks = [c for lang, c in fenced_blocks(body) if lang in ("yaml", "yml")]
    assert yaml_blocks, "expected at least one yaml example block"
    for block in yaml_blocks:
        yaml.safe_load(block)


@pytest.mark.parametrize("skill_path", skill_files(), ids=lambda p: p.parent.name)
def test_skill_image_tag_contract(skill_path):
    """Every container declared in the skill's stack.yml examples must be
    referenced as `<name>:stack` in one of its composefile examples — the
    contract the skill itself teaches."""
    _, body = parse_skill(skill_path)
    docs = [yaml.safe_load(c) for lang, c in fenced_blocks(body) if lang in ("yaml", "yml")]
    container_names = []
    images = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        for container in doc.get("containers") or []:
            if isinstance(container, dict) and "name" in container:
                container_names.append(container["name"])
        for service in (doc.get("services") or {}).values():
            if isinstance(service, dict) and "image" in service:
                images.append(service["image"])
    assert container_names, "expected a stack.yml example declaring containers"
    for name in container_names:
        assert f"{name}:stack" in images, (
            f"container `{name}` is not referenced as `{name}:stack` in any composefile example"
        )


@pytest.mark.parametrize("skill_path", skill_files(), ids=lambda p: p.parent.name)
def test_skill_repo_links_resolve(skill_path):
    """Links into this repo's main branch must point at files that exist."""
    text = skill_path.read_text()
    refs = re.findall(r"https://github\.com/bozemanpass/stack/(?:blob|tree)/main/([^\s)\"'`]+)", text)
    assert refs, "expected at least one docs link"
    for ref in refs:
        assert (REPO_ROOT / ref).exists(), f"link target `{ref}` does not exist in the repo"


def _invocation_params():
    params = []
    for skill_path in skill_files():
        for line, tokens in stack_invocations(skill_path):
            params.append(pytest.param(tokens, id=f"{skill_path.parent.name}: {line}"))
    return params


@pytest.mark.parametrize("tokens", _invocation_params())
def test_skill_cli_invocations(tokens, cli_tree):
    validate_invocation(tokens, cli_tree)


def test_skill_invocations_extracted():
    """Guard the extractor itself: if it silently matched nothing, every
    invocation test above would vacuously pass."""
    assert len(_invocation_params()) >= 10


def test_plugin_manifest():
    manifest = json.loads(PLUGIN_MANIFEST.read_text())
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", manifest["name"]), "plugin name must be kebab-case"
    assert skill_files(), "plugin declares no skills"
