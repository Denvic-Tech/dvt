"""Layout integration: translate failures and select actual position changes."""

from dataclasses import dataclass

from ..errors import AIMCPHTTPError
from .layout import LayoutError, calculate_layout
from .layout.geometry import Rect
from .state import GraphState, PositionChanges


@dataclass(frozen=True)
class Arrangement:
    positions: PositionChanges
    bounds: Rect


def arrange_graph(
    graph: GraphState,
    *,
    before: GraphState | None = None,
    full: bool = False,
) -> Arrangement:
    try:
        layout = calculate_layout(graph, before=before, full=full)
    except LayoutError as exc:
        raise AIMCPHTTPError(422, "GRAPH_LAYOUT_FAILED", str(exc)) from exc
    return Arrangement(
        positions=PositionChanges(
            nodes={
                node_id: position
                for node_id, position in layout.node_positions.items()
                if graph.nodes[node_id].position != position
            },
            subgraphs={
                group_id: position
                for group_id, position in layout.subgraph_positions.items()
                if graph.subgraphs[group_id].position != position
            },
        ),
        bounds=layout.bounds,
    )
