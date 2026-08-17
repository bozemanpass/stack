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

# Validates docs/test-coverage.md, the cross-reference from commands and
# functional areas to test code.  The page anchors entries by test file and
# step name rather than line number precisely so that it can be checked: every
# file it links must exist, and every step it quotes must appear verbatim in
# the script it is attributed to.  Renaming a step or moving a test therefore
# fails here until the index is updated, instead of the page rotting silently.

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
COVERAGE_DOC = REPO_ROOT / "docs" / "test-coverage.md"

LINK_PATTERN = re.compile(r"\[[^\]]*\]\((\.\./tests/[^)]+)\)")
STEP_PATTERN = re.compile(r"`([^`]+)`")


def _table_rows():
    """Yield (script_path, [step, ...]) for each table row naming a test script.

    A row's Test cell holds the script link and its Step cell the backticked
    step names; links are stripped from the Step cell first, so a parenthetical
    pointer like "(see [`tests/k3s-deploy/`](...))" is not mistaken for a step.
    """
    rows = []
    for line in COVERAGE_DOC.read_text().splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        script_links = [t for t in LINK_PATTERN.findall(cells[1]) if t.endswith(".sh")]
        if not script_links:
            continue
        step_cell = LINK_PATTERN.sub("", cells[2])
        rows.append((script_links[0], STEP_PATTERN.findall(step_cell)))
    return rows


def test_coverage_doc_exists():
    assert COVERAGE_DOC.exists(), f"{COVERAGE_DOC} not found"


def test_every_linked_path_exists():
    targets = LINK_PATTERN.findall(COVERAGE_DOC.read_text())
    assert targets, "no test links found; has the page's link format changed?"
    for target in targets:
        resolved = (COVERAGE_DOC.parent / target).resolve()
        assert resolved.exists(), f"{target} is linked from test-coverage.md but does not exist"


def test_every_step_appears_in_its_script():
    rows = _table_rows()
    assert rows, "no table rows with test links found; has the page's table format changed?"
    for script, steps in rows:
        script_text = (COVERAGE_DOC.parent / script).resolve().read_text()
        for step in steps:
            assert step in script_text, (
                f"test-coverage.md names step '{step}' in {script}, but the script does not contain it"
            )


@pytest.mark.parametrize("step_marker", ["deploy update config", "deploy update content"])
def test_known_steps_are_indexed(step_marker):
    # Spot-check the inverse direction for a couple of load-bearing steps: the
    # page should not quietly lose its entries while remaining self-consistent.
    doc_text = COVERAGE_DOC.read_text()
    assert f"`{step_marker}`" in doc_text, f"step '{step_marker}' is no longer indexed in test-coverage.md"
