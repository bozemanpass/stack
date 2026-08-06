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

"""Tests for the mermaid renderer behind `stack chart`."""

from stack.chart.chart import _render_stack_mermaid, _split_volume

# The same stand-in stack the text renderer is tested against, so the two
# renderings can be compared on identical input.
from test_chart_text import FakeStack, _todo_stack


def _render(stack, show_http_targets=True, show_ports=False, show_volumes=True, direction="LR"):
    return _render_stack_mermaid(stack, show_http_targets, show_ports, show_volumes, direction)


def test_split_volume_separates_name_from_mount():
    assert _split_volume("db-data:/var/lib/postgresql/data") == ("db-data", "/var/lib/postgresql/data")
    # An anonymous volume has no name to split off.
    assert _split_volume("db-data") == ("db-data", "")


def test_flowchart_direction_defaults_to_left_to_right():
    assert _render(_todo_stack())[0] == "flowchart LR"


def test_flowchart_direction_is_selectable():
    assert _render(_todo_stack(), direction="TD")[0] == "flowchart TD"


def test_a_subgraph_does_not_override_the_chart_direction():
    # Subgraphs emit their own `direction` line, which mermaid honours over the
    # chart's, so the renderer drops them.
    assert not any("direction" in line for line in _render(_todo_stack())[1:])


def test_services_are_drawn_inside_the_stack_subgraph():
    lines = _render(_todo_stack())
    assert "  subgraph todo [todo]" in lines
    assert any("todo-backend[[backend]]" in line for line in lines)
    assert any("todo-db[[db]]" in line for line in lines)


def test_depends_on_is_drawn_as_an_edge():
    # The whole point of the diagram: backend needs db, so there is an arrow.
    assert any(line.strip() == "todo-backend --> todo-db" for line in _render(_todo_stack()))


def test_dependency_edges_survive_forward_references():
    # depends_on routinely names a service declared later in the compose file.
    stack = FakeStack(
        "app",
        services={"web": {"image": "nginx:1", "depends_on": ["api"]}, "api": {"image": "org/api:stack"}},
    )
    assert any(line.strip() == "app-web --> app-api" for line in _render(stack))


def test_a_dependency_on_an_unknown_service_is_skipped():
    stack = FakeStack("app", services={"web": {"image": "nginx:1", "depends_on": ["nowhere"]}})
    assert not any("nowhere" in line for line in _render(stack))


def test_a_volume_node_carries_only_its_name():
    lines = _render(_todo_stack())
    assert any("todo-db-volume-db-data(db-data)" in line for line in lines)
    # The mount path is long enough to stretch the subgraph, so it rides on the edge.
    assert any("todo-db --> |/var/lib/postgresql/data|todo-db-volume-db-data" in line for line in lines)


def test_http_targets_become_ingress_nodes():
    lines = _render(_todo_stack())
    assert any('todo-backend-http>":5000 (/api/todos)"]' in line for line in lines)
    assert any(line.strip() == "todo-backend-http --> todo-backend" for line in lines)
    # A service with a route is styled as an http service rather than a plain one.
    assert any("todo-backend[[backend]]:::http_service" in line for line in lines)
    assert any("todo-db[[db]]:::service" in line for line in lines)


def test_sections_can_be_suppressed():
    lines = _render(_todo_stack(), show_http_targets=False, show_volumes=False)
    assert not any("-http" in line for line in lines)
    assert not any("volume" in line for line in lines)


def test_ports_are_hidden_by_default():
    assert not any("-port-" in line for line in _render(_todo_stack()))
    assert any("-port-" in line for line in _render(_todo_stack(), show_ports=True))


def test_only_the_classes_in_use_are_defined():
    lines = _render(_todo_stack())
    defined = {line.split()[1] for line in lines if line.strip().startswith("classDef")}
    assert defined == {"stack", "service", "http_service", "http_target", "volume"}
    # Ports are not shown, and this is not a super stack, so those styles are noise.
    assert "port" not in defined
    assert "super_stack" not in defined


def test_super_stack_children_are_nested_subgraphs(monkeypatch):
    from stack.chart import chart

    child = FakeStack("web", services={"nginx": {"image": "nginx:1"}})
    parent = FakeStack("platform", required=["path-a"])
    monkeypatch.setattr(chart, "resolve_stack", lambda path: child)

    lines = _render(parent)

    assert any("subgraph platform [platform]" in line for line in lines)
    assert any("subgraph web [web]" in line for line in lines)
    assert any("classDef super_stack" in line for line in lines)
