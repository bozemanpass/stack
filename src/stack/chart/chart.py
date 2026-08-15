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

from mermaid_builder.flowchart import Chart, Node, NodeShape, Subgraph, ChartDir, ClassDef

from stack.deploy.stack import resolve_stack
from stack.log import output_main

_theme = {
    "super_stack": "stroke:#FFF176,fill:#FFFEEF,color:#6B5E13,stroke-width:2px,font-size:small;",
    "stack": "stroke:#00C9A7,fill:#EDFDFB,color:#1A3A38,stroke-width:2px,font-size:small;",
    "service": "stroke:#43E97B,fill:#F5FFF7,color:#236247,stroke-width:2px;",
    "http_service": "stroke:#FFB236,fill:#FFFAF4,color:#7A5800,stroke-width:2px;",
    "http_target": "stroke:#FF6363,fill:#FFF5F5,color:#7C2323,stroke-width:2px;",
    "port": "stroke:#26C6DA,fill:#E6FAFB,color:#074953,stroke-width:2px,font-size:x-small;",
    "volume": "stroke:#A259DF,fill:#F4EEFB,color:#320963,stroke-width:2px,font-size:x-small;",
}


def _image_summary(svc_config):
    """One-line description of what a service runs, and whether it is built here."""
    image = svc_config.get("image") or "?"
    build = svc_config.get("build")
    if isinstance(build, dict):
        build = build.get("context")
    return f"{image} (build {build})" if build else image


def _depends_on(svc_config):
    depends = svc_config.get("depends_on") or []
    # Compose allows either a plain list or a mapping of name -> condition.
    return list(depends.keys()) if isinstance(depends, dict) else list(depends)


def _split_volume(volume):
    """Split a compose volume ('name:/mount') into its name and mount point."""
    volume_name, _, mount = str(volume).partition(":")
    return volume_name, mount


def _used_class_names(chart):
    """Every class actually referenced by a chart and its subgraphs."""
    used = {node.class_name for node in chart.nodes if node.class_name}
    used.update(attachment.class_name for attachment in chart.class_attachments)
    for subgraph in chart.subgraphs:
        used.update(_used_class_names(subgraph))
    return used


def _render_stack_text(stack, show_http_targets, show_ports, show_volumes, indent="", lines=None):
    """Render the stack as an indented tree, mirroring what the mermaid chart shows."""
    if lines is None:
        lines = []
    lines.append(f"{indent}{stack.name}")

    if stack.is_super_stack():
        children = stack.get_required_stacks_paths()
        for i, child in enumerate(children):
            last_child = i == len(children) - 1
            branch = "└── " if last_child else "├── "
            child_indent = indent + ("    " if last_child else "│   ")
            child_stack = resolve_stack(child)
            # Render the child at its own indent, then replace its root line so the child
            # stack hangs off this stack's branch instead of being indented under it.
            child_lines = _render_stack_text(child_stack, show_http_targets, show_ports, show_volumes, child_indent, [])
            child_lines[0] = f"{indent}{branch}{child_stack.name}"
            lines.extend(child_lines)
        return lines

    services = stack.get_services()
    http_targets = stack.get_http_proxy_targets() if show_http_targets else []
    ports = stack.get_ports() if show_ports else {}
    volumes = stack.get_volumes() if show_volumes else {}
    # The stack's backup setup (see docs/backup.md), so what a backup would and
    # would not capture is visible without deploying anything.
    backup_targets = stack.get_backup_targets()
    backup_exclude = set(backup_targets["exclude"])
    backup_commands = backup_targets["commands"]

    name_width = max((len(s) for s in services), default=0)
    service_names = list(services)
    for i, svc in enumerate(service_names):
        last = i == len(service_names) - 1
        branch = "└── " if last else "├── "
        # Detail lines hang under the service, so they need the continuation bar.
        detail_indent = indent + ("      " if last else "│     ")
        lines.append(f"{indent}{branch}{svc.ljust(name_width)}  {_image_summary(services[svc])}")

        for ht in [t for t in http_targets if t["service"] == svc]:
            lines.append(f"{detail_indent}http :{ht['port']} -> {ht.get('path', '/')}")

        shown_http_ports = {str(t["port"]) for t in http_targets if t["service"] == svc}
        for port in ports.get(svc, []):
            # Skip ports already shown as an http route to avoid saying the same thing twice.
            if str(port).split(":")[-1] in shown_http_ports:
                continue
            lines.append(f"{detail_indent}port {port}")

        for volume in volumes.get(svc, []):
            volume_name, mount = _split_volume(volume)
            excluded = " (backup excluded)" if volume_name in backup_exclude else ""
            lines.append(f"{detail_indent}volume {volume_name}" + (f" -> {mount}" if mount else "") + excluded)

        if svc in backup_commands:
            extension = backup_commands[svc].get("file-extension")
            suffix = f" (.{extension})" if extension else ""
            lines.append(f"{detail_indent}backup dump {backup_commands[svc]['command']}{suffix}")

        for dep in _depends_on(services[svc]):
            lines.append(f"{detail_indent}needs {dep}")

    return lines


def _add_http_targets(chart, stack, svc, svc_node, parent_stack):
    """Attach an ingress node per http-proxy target, and return the ports so attached."""
    attached = set()
    for ht in stack.get_http_proxy_targets():
        if ht["service"] != svc:
            continue
        path = ht.get("path", "/")
        if parent_stack:
            http_prefix = parent_stack.http_prefix_for(stack.file_path.parent)
            if http_prefix and http_prefix != "/":
                path = f"{http_prefix}{path}"
        attached.add(ht["port"])

        http_node = Node(
            id=f"{stack.name}-{svc}-http",
            title=f'''":{ht['port']} ({path})"''',
            shape=NodeShape.ASSYMETRIC,
            class_name="http_target",
        )
        chart.add_node(http_node)
        chart.add_link_between(http_node, svc_node)
        svc_node.class_name = "http_service"
    return attached


def _add_ports(chart, stack, svc, svc_node, shown_http_ports):
    for port in stack.get_ports().get(svc, []):
        if port in shown_http_ports:
            continue
        port_node = Node(id=f"{stack.name}-{svc}-port-{port}", title=f":{port}", shape=NodeShape.ASSYMETRIC, class_name="port")
        chart.add_node(port_node)
        chart.add_link_between(port_node, svc_node)


def _add_volumes(subgraph, stack, svc, svc_node):
    for volume in stack.get_volumes().get(svc, []):
        # Only the volume's name goes in the node: the mount path is long enough to
        # stretch the whole subgraph to fit it, so it rides on the edge instead.
        volume_name, mount = _split_volume(volume)
        volume_node = Node(
            id=f"{stack.name}-{svc}-volume-{volume_name}",
            title=volume_name,
            shape=NodeShape.RECT_ROUND,
            class_name="volume",
        )
        subgraph.add_node(volume_node)
        subgraph.add_link_between(svc_node, volume_node, text=mount or None)


def _add_stack(chart, stack, show_http_targets, show_ports, show_volumes, parent_graph=None, parent_stack=None):
    subgraph = Subgraph(stack.name)
    subgraph.get_id()  # we need this to be set

    if stack.is_super_stack():
        chart.attach_class(subgraph.title, "super_stack")
        for child in stack.get_required_stacks_paths():
            child = resolve_stack(child)
            _add_stack(chart, child, show_http_targets, show_ports, show_volumes, parent_graph=subgraph, parent_stack=stack)
    else:
        chart.attach_class(subgraph.title, "stack")

    services = stack.get_services()
    svc_nodes = {}

    for svc in services:
        svc_node = Node(id=f"{stack.name}-{svc}", title=svc, shape=NodeShape.SUBROUTINE, class_name="service")
        subgraph.add_node(svc_node)
        svc_nodes[svc] = svc_node

        shown_http_ports = _add_http_targets(chart, stack, svc, svc_node, parent_stack) if show_http_targets else set()
        if show_ports:
            _add_ports(chart, stack, svc, svc_node, shown_http_ports)
        if show_volumes:
            _add_volumes(subgraph, stack, svc, svc_node)

    # Dependencies are drawn once every service node exists, since depends_on
    # routinely names a service declared later in the file.
    for svc, svc_node in svc_nodes.items():
        for dep in _depends_on(services[svc]):
            if dep in svc_nodes:
                subgraph.add_link_between(svc_node, svc_nodes[dep])

    if parent_graph:
        for s in parent_graph.subgraphs:
            if s.id != subgraph.id:
                chart.add_link_between(s.id, subgraph.id)
                chart.add_link_between(subgraph.id, s.id)
        parent_graph.add_subgraph(subgraph)
    else:
        chart.add_subgraph(subgraph)


def _render_stack_mermaid(stack, show_http_targets, show_ports, show_volumes, direction):
    """Render the stack as the lines of a mermaid flowchart."""
    chart = Chart(direction=ChartDir[direction])
    _add_stack(chart, stack, show_http_targets, show_ports, show_volumes)

    # Styling the whole theme regardless of what is on the chart leaves unreferenced
    # classDef lines in the output, which is noise wherever the diagram gets pasted.
    used = _used_class_names(chart)
    for cls, style in _theme.items():
        if cls in used:
            chart.add_class_def(ClassDef(cls, f"{style}"))

    # A subgraph's own direction would override the one asked for on the command line.
    return [line for line in str(chart).splitlines() if "direction" not in line]


@click.command()
@click.option("--stack", help="name or path of the stack", required=False)
@click.option("--show-ports/--no-show-ports", default=False)
@click.option("--show-http-targets/--no-show-http-targets", default=True)
@click.option("--show-volumes/--no-show-volumes", default=True)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["mermaid", "text"]),
    default="mermaid",
    help="render as a mermaid diagram, or as a plain text tree",
)
@click.option(
    "--direction",
    type=click.Choice([d.name for d in ChartDir]),
    default=ChartDir.LR.name,
    help="direction the mermaid diagram flows in",
)
@click.pass_context
def command(ctx, stack, show_ports, show_http_targets, show_volumes, output_format, direction):
    """generate a mermaid graph of the stack"""

    parent_stack = resolve_stack(stack)

    if output_format == "text":
        for line in _render_stack_text(parent_stack, show_http_targets, show_ports, show_volumes):
            output_main(line)
        return

    for line in _render_stack_mermaid(parent_stack, show_http_targets, show_ports, show_volumes, direction):
        output_main(line)
