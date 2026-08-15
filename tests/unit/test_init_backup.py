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

"""How `stack init` records the @stack backup-* annotations in the output spec.

The annotations are author-time metadata in the composefile; the spec's `backup`
section is how they reach deploy time (the Docker target's env injection and the
Kubernetes object generation both read the spec, not the composefile).
"""

import yaml

from conftest import make_stack_from_compose, run_stack

BACKUP_POD = """\
    services:
      db:
        image: postgres:local
        volumes:
          - pgdata:/var/lib/postgresql/data   # @stack backup-exclude
        # @stack backup-command pg_dump -U postgres -d todos
        # @stack backup-file-extension sql
    volumes:
      pgdata:
    """


def init_spec(stack_dir, output_file, env):
    result = run_stack(["init", "--stack", str(stack_dir), "--output", str(output_file)], env)
    assert result.returncode == 0, result.stderr
    return yaml.safe_load(output_file.read_text())


def test_backup_annotations_recorded_in_spec(tmp_path, isolated_env):
    stack_dir = make_stack_from_compose(tmp_path, BACKUP_POD)
    spec = init_spec(stack_dir, tmp_path / "spec.yml", isolated_env)
    assert spec["backup"] == {
        "exclude": ["pgdata"],
        "commands": {"db": {"command": "pg_dump -U postgres -d todos", "file-extension": "sql"}},
    }


def test_no_backup_section_without_annotations(tmp_path, isolated_env):
    stack_dir = make_stack_from_compose(
        tmp_path,
        """\
        services:
          web:
            image: nginx:local
        """,
    )
    spec = init_spec(stack_dir, tmp_path / "spec.yml", isolated_env)
    assert "backup" not in spec
