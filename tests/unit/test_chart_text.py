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

"""Tests for the plain text renderer behind `stack chart --format text`."""

from stack.chart import chart
from stack.chart.chart import _depends_on, _image_summary, _render_stack_text


class FakeStack:
    """Stands in for a Stack; the text renderer only reads these accessors."""

    def __init__(self, name, services=None, http_targets=None, ports=None, volumes=None, required=None, backup=None):
        self.name = name
        self._services = services or {}
        self._http_targets = http_targets or []
        self._ports = ports or {}
        self._volumes = volumes or {}
        self._required = required or []
        self._backup = backup or {"exclude": [], "commands": {}}

    def is_super_stack(self):
        return bool(self._required)

    def get_required_stacks_paths(self):
        return list(self._required)

    def get_services(self):
        return self._services

    def get_http_proxy_targets(self):
        return self._http_targets

    def get_ports(self):
        return self._ports

    def get_volumes(self):
        return self._volumes

    def get_backup_targets(self):
        return self._backup


def _todo_stack():
    return FakeStack(
        "todo",
        services={
            "backend": {"image": "org/backend:stack", "build": "./backend", "depends_on": {"db": {"condition": "healthy"}}},
            "frontend": {"image": "org/frontend:stack", "build": "./frontend"},
            "db": {"image": "postgres:14"},
        },
        http_targets=[
            {"service": "backend", "port": "5000", "path": "/api/todos"},
            {"service": "frontend", "port": "3000", "path": "/"},
        ],
        ports={"backend": ["5000:5000"], "frontend": ["3000:3000"], "db": ["5432:5432"]},
        volumes={"db": ["db-data:/var/lib/postgresql/data"]},
    )


def _render(stack, show_http_targets=True, show_ports=False, show_volumes=True):
    return _render_stack_text(stack, show_http_targets, show_ports, show_volumes)


# ---------------------------------------------------------------------------
# _image_summary / _depends_on
# ---------------------------------------------------------------------------


def test_image_summary_notes_locally_built_images():
    assert _image_summary({"image": "org/app:stack", "build": "./app"}) == "org/app:stack (build ./app)"


def test_image_summary_plain_for_pulled_images():
    assert _image_summary({"image": "postgres:14"}) == "postgres:14"


def test_image_summary_accepts_build_as_a_mapping():
    # Compose allows `build:` to be a mapping with a context rather than a bare string.
    assert _image_summary({"image": "org/app:stack", "build": {"context": "./app"}}) == "org/app:stack (build ./app)"


def test_image_summary_tolerates_a_missing_image():
    assert _image_summary({}) == "?"


def test_depends_on_handles_both_compose_forms():
    assert _depends_on({"depends_on": ["db"]}) == ["db"]
    assert _depends_on({"depends_on": {"db": {"condition": "healthy"}}}) == ["db"]
    assert _depends_on({}) == []


# ---------------------------------------------------------------------------
# tree rendering
# ---------------------------------------------------------------------------


def test_renders_services_under_the_stack_name():
    lines = _render(_todo_stack())
    assert lines[0] == "todo"
    assert any(line.startswith("├── backend") for line in lines)
    # The final service uses the closing branch.
    assert any(line.startswith("└── db") for line in lines)


def test_service_names_are_aligned():
    lines = _render(_todo_stack())
    service_lines = [line for line in lines if line.startswith(("├── ", "└── "))]
    # Each service's image summary should begin at the same column.
    offsets = {line.index("org/") if "org/" in line else line.index("postgres") for line in service_lines}
    assert len(offsets) == 1


def test_http_routes_are_shown_for_the_owning_service():
    lines = _render(_todo_stack())
    assert any("http :5000 -> /api/todos" in line for line in lines)
    assert any("http :3000 -> /" in line for line in lines)


def test_dependencies_and_volumes_are_shown():
    lines = _render(_todo_stack())
    assert any("needs db" in line for line in lines)
    assert any("volume db-data -> /var/lib/postgresql/data" in line for line in lines)


def test_ports_are_hidden_by_default():
    assert not any("port " in line for line in _render(_todo_stack()))


def test_show_ports_omits_ports_already_shown_as_http_routes():
    lines = _render(_todo_stack(), show_ports=True)
    # db's port is not an http route, so it is worth showing...
    assert any("port 5432:5432" in line for line in lines)
    # ...but the http services' ports would just repeat the route lines.
    assert not any("port 5000:5000" in line for line in lines)
    assert not any("port 3000:3000" in line for line in lines)


def test_backup_setup_is_shown():
    stack = _todo_stack()
    stack._backup = {
        "exclude": ["db-data"],
        "commands": {"db": {"command": "pg_dump -U postgres todos", "file-extension": "sql"}},
    }
    lines = _render(stack)
    assert any("volume db-data -> /var/lib/postgresql/data (backup excluded)" in line for line in lines)
    assert any("backup dump pg_dump -U postgres todos (.sql)" in line for line in lines)


def test_no_backup_lines_without_backup_annotations():
    lines = _render(_todo_stack())
    assert not any("backup" in line for line in lines)


def test_sections_can_be_suppressed():
    lines = _render(_todo_stack(), show_http_targets=False, show_volumes=False)
    assert not any("http :" in line for line in lines)
    assert not any("volume " in line for line in lines)


def test_super_stack_nests_its_children(monkeypatch):
    child_a = FakeStack("web", services={"nginx": {"image": "nginx:1"}})
    child_b = FakeStack("api", services={"app": {"image": "org/api:stack"}})
    parent = FakeStack("platform", required=["path-a", "path-b"])

    by_path = {"path-a": child_a, "path-b": child_b}
    monkeypatch.setattr(chart, "resolve_stack", lambda path: by_path[path])

    lines = _render(parent)

    assert lines[0] == "platform"
    # Each child stack hangs off the parent, keeping its own name as the subtree root.
    assert "├── web" in lines
    assert "└── api" in lines
    # A non-final child's services stay under the continuation bar.
    assert any(line.startswith("│   └── nginx") for line in lines)
    # The final child's services are no longer under a bar.
    assert any(line.startswith("    └── app") for line in lines)
