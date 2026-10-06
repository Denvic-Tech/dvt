"""Pure layout calculation: validate, select, build blocks, place."""

from ..state import GraphState
from .blocks import build_blocks
from .geometry import LayoutResult
from .placement import place_components
from .topology import LayoutScope, affected_scope, check_structure


def calculate_layout(
    graph: GraphState,
    *,
    before: GraphState | None = None,
    full: bool = False,
) -> LayoutResult:
    check_structure(graph)
    before = before if before is not None else GraphState()
    scope = (
        LayoutScope(set(graph.nodes), set(graph.subgraphs))
        if full
        else affected_scope(before, graph)
    )
    blocks = build_blocks(graph, scope)
    return place_components(blocks, graph, before, full=full)
