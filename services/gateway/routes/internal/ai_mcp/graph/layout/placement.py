"""Place affected components against fixed geometry, then expand subgraph blocks."""

from ..state import GraphState, Position
from .blocks import LayoutBlocks, position_of
from .geometry import (
    COMPONENT_GAP,
    ORIGIN,
    LayoutError,
    LayoutResult,
    Rect,
    assert_disjoint,
    bounding_rect,
)
from .layers import layered_layout
from .topology import BlockKey, connected_components


def _anchor(
    component: set[BlockKey],
    graph: GraphState,
    before: GraphState,
    obstacles: list[Rect],
    *,
    full: bool,
) -> Position:
    anchors = []
    if not full:
        for key in component:
            old = (
                before.nodes.get(key.entity_id)
                if key.kind == "node"
                else graph.subgraphs[key.entity_id]
            )
            if old is not None and old.position is not None:
                anchors.append(position_of(old))
    default_y = max((rect.bottom for rect in obstacles), default=ORIGIN - COMPONENT_GAP)
    return Position(
        min((position.x for position in anchors), default=ORIGIN),
        min((position.y for position in anchors), default=default_y + COMPONENT_GAP),
    )


def _avoid_obstacles(anchor: Position, bounds: Rect, obstacles: list[Rect]) -> Rect:
    y = anchor.y
    while True:
        block = Rect(anchor.x, y, bounds.width, bounds.height)
        collisions = [rect for rect in obstacles if block.intersects(rect)]
        if not collisions:
            return block
        y = max(rect.bottom for rect in collisions) + COMPONENT_GAP


def _expand_positions(
    result: LayoutResult,
    rectangles: dict[BlockKey, Rect],
    block: Rect,
    internal: dict[str, dict[str, Rect]],
) -> None:
    for key, rect in rectangles.items():
        position = Position(block.x + rect.x, block.y + rect.y)
        if key.kind == "node":
            result.node_positions[key.entity_id] = position
            continue
        result.subgraph_positions[key.entity_id] = position
        for node_id, member in internal[key.entity_id].items():
            result.node_positions[node_id] = Position(
                position.x + member.x,
                position.y + member.y,
            )


def place_components(
    blocks: LayoutBlocks,
    graph: GraphState,
    before: GraphState,
    *,
    full: bool,
) -> LayoutResult:
    placed: list[Rect] = []
    result = LayoutResult({}, {}, Rect(0, 0, 0, 0))
    components = sorted(
        connected_components(blocks.sizes, blocks.edges),
        key=lambda items: min(blocks.order[key] for key in items),
    )
    for component in components:
        edges = {
            (source, target)
            for source, target in blocks.edges
            if source in component and target in component
        }
        placement = layered_layout(
            {key: blocks.sizes[key] for key in component},
            edges,
            blocks.order,
        )
        assert_disjoint(placement.rectangles.values())
        obstacles = [*blocks.obstacles, *placed]
        anchor = _anchor(component, graph, before, obstacles, full=full)
        block = _avoid_obstacles(anchor, placement.bounds, obstacles)
        placed.append(block)
        _expand_positions(result, placement.rectangles, block, blocks.internal)
    # Existing overlaps outside the affected area do not invalidate this edit.
    assert_disjoint(placed)
    if any(block.intersects(obstacle) for block in placed for obstacle in blocks.obstacles):
        raise LayoutError("Calculated component overlaps unchanged graph geometry.")
    result.bounds = bounding_rect([*blocks.obstacles, *placed])
    return result
