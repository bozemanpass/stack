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

from stack.config.util import get_config_setting
from stack.deploy.stack import resolve_stack
from stack.log import output_main


_theme = {
    "super_stack": "stroke-width:1px, stroke-dasharray:none, stroke:#254336, fill:#27654A, color:#FFFFFF",
    "stack": "stroke-width:1px, stroke-dasharray:none, stroke:#46EDC8, fill:#DEFFF8, color:#378E7A",
    "service": "stroke-width:1px, stroke-dasharray:none, stroke:#374D7C, fill:#E2EBFF, color:#374D7C",
    "http_service": "stroke-width:1px, stroke-dasharray:none, stroke:#FBB35A, fill:#FFF9C4, color:#AE4466",
    "http_port": "stroke-width:1px, stroke-dasharray:none, stroke:#FFEFDB, fill:#FBB35A, color:#AE4466",
}


@click.command()
@click.option("--stack", help="name or path of the stack", required=False)
@click.option(
    "--deploy-to",
    help="cluster system to deploy to (compose or k8s or k8s-kind)",
    default=get_config_setting("deploy-to", "compose"),
)
@click.pass_context
def command(ctx, stack, deploy_to):
    """generate a mermaid graph of the stack"""

    parent_stack = resolve_stack(stack)
    chart = Chart(direction=ChartDir.RL)

    for cls, style in _theme.items():
        chart.add_class_def(ClassDef(cls, f"{cls} {style}"))

    def add_stack(stack, parent_graph=None, parent_stack=None):
        subgraph = Subgraph(stack.name)
        subgraph.get_id()  # we need this to be set

        if stack.is_super_stack():
            chart.attach_class(subgraph.title, "super_stack")
            for child in stack.get_required_stacks_paths():
                child = resolve_stack(child)
                add_stack(child, parent_graph=subgraph, parent_stack=stack)
        else:
            chart.attach_class(subgraph.title, "stack")

        for svc in stack.get_services():
            svc_node = Node(id=f"{stack.name}-{svc}", title=svc, shape=NodeShape.SUBROUTINE, class_name="service")
            subgraph.add_node(svc_node)
            http_targets = stack.get_http_proxy_targets()
            for ht in http_targets:
                if ht["service"] == svc:
                    title = f":{ht['port']}{ht.get('path', '')}"
                    if "k8s" in deploy_to and parent_stack:
                        title = ht.get("path", "/")
                        http_prefix = parent_stack.http_prefix_for(stack.file_path.parent)
                        if http_prefix and http_prefix != "/":
                            title = f"{http_prefix}{title}"

                    http_node = Node(id=f"{stack.name}-{svc}-http", title=title, shape=NodeShape.ASSYMETRIC, class_name="http_port")
                    chart.add_node(http_node)
                    chart.add_link_between(http_node, svc_node)
                    svc_node.class_name = "http_service"
        if parent_graph:
            for s in parent_graph.subgraphs:
                if s.id != subgraph.id:
                    chart.add_link_between(s.id, subgraph.id)
                    chart.add_link_between(subgraph.id, s.id)
            parent_graph.add_subgraph(subgraph)
        else:
            chart.add_subgraph(subgraph)

    add_stack(parent_stack)

    out = str(chart)
    for line in out.splitlines():
        if "direction" not in line:
            output_main(line)
