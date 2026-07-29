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

"""Every module must be importable on its own.

The package has import cycles that resolve only for some entry orders: a module-level
`import x.y as z` tolerates a partially initialized module but `from x.y import name`
does not.  The CLI happens to import in a working order, so a cycle that breaks direct
imports is invisible until something else -- a test, a plugin, a new command -- imports
a module first.  Each module is imported in its own subprocess so that one test cannot
prime sys.modules for another.
"""

import pkgutil
import subprocess
import sys

import pytest

import stack


def stack_modules():
    names = []
    for module in pkgutil.walk_packages(stack.__path__, prefix="stack."):
        # stack.data holds templates and embedded component YAML, not code.
        if module.name.startswith("stack.data"):
            continue
        names.append(module.name)
    return sorted(names)


@pytest.mark.parametrize("module_name", stack_modules())
def test_module_imports_standalone(module_name, isolated_env):
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        env=isolated_env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"import {module_name} failed:\n{result.stderr}"
