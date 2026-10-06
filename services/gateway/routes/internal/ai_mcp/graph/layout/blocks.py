"""Convert nodes and subgraphs into external layout blocks."""

from collections import defaultdict
from dataclasses import dataclass, field

from ..state import GraphState, NodeState, Position, SubgraphState
from .geometry import (
    COLLAPSED_HEIGHT,
    COLLAPSED_WIDTH,
    GROUP_MIN_HEIGHT,
    GROUP_MIN_WIDTH,
    GROUP_PADDING_BOTTOM,
    GROUP_PADDING_TOP,
    GROUP_PADDING_X,
    NODE_HEIGHT,
    NODE_WIDTH,
    OrderKey,
    Rect,
    Size,
    assert_disjoint,
    bounding_rect,
)
from .layers import pack_components
from .topology import BlockKey, LayoutScope


@dataclass
class LayoutBlocks:
    sizes: dict[BlockKey, Size] = field(default_factory=dict)
    order: dict[BlockKey, OrderKey] = field(default_factory=dict)
    edges: set[tuple[BlockKey, BlockKey]] = field(default_factory=set)
    internal: dict[str, dict[str, Rect]] = field(default_factory=dict)
    obstacles: list[Rect] = field(default_factory=list)


def position_of(item: NodeState | SubgraphState) -> Position:
    return item.position if item.position is not None else Position(0.0, 0.0)


def stable_order(item: NodeState | SubgraphState, kind: str = "") -> OrderKey:
    position = position_of(item)
    return OrderKey(position.y, position.x, item.id, kind)


def group_rect(group: SubgraphState, members: list[NodeState]) -> Rect:
    position = position_of(group)
    if not group.expanded:
        return Rect(position.x, position.y, COLLAPSED_WIDTH, COLLAPSED_HEIGHT)
    if not members:
        return Rect(position.x, position.y, GROUP_MIN_WIDTH, GROUP_MIN_HEIGHT)
    bounds = bounding_rect(
        Rect(position_of(node).x, position_of(node).y, NODE_WIDTH, NODE_HEIGHT) for node in members
    )
    # Expanded panels are derived by the UI from absolute member coordinates.
    return Rect(
        bounds.x - GROUP_PADDING_X,
        bounds.y - GROUP_PADDING_TOP,
        max(GROUP_MIN_WIDTH, bounds.width + 2 * GROUP_PADDING_X),
        max(GROUP_MIN_HEIGHT, bounds.height + GROUP_PADDING_TOP + GROUP_PADDING_BOTTOM),
    )


def _add_group_block(
    blocks: LayoutBlocks,
    graph: GraphState,
    group: SubgraphState,
    members: list[NodeState],
) -> None:
    member_ids = {node.id for node in members}
    edges = {
        (edge.source, edge.target)
        for edge in graph.edges.values()
        if edge.source in member_ids and edge.target in member_ids
    }
    placement = pack_components(
        dict.fromkeys(member_ids, Size(NODE_WIDTH, NODE_HEIGHT)),
        edges,
        {node.id: stable_order(node) for node in members},
    )
    internal = {
        node_id: rect.translated(GROUP_PADDING_X, GROUP_PADDING_TOP)
        for node_id, rect in placement.rectangles.items()
    }
    assert_disjoint(internal.values())
    blocks.internal[group.id] = internal
    if group.expanded:
        size = Size(
            max(GROUP_MIN_WIDTH, placement.bounds.width + 2 * GROUP_PADDING_X),
            max(
                GROUP_MIN_HEIGHT, placement.bounds.height + GROUP_PADDING_TOP + GROUP_PADDING_BOTTOM
            ),
        )
    else:
        size = Size(COLLAPSED_WIDTH, COLLAPSED_HEIGHT)
    key = BlockKey("group", group.id)
    blocks.sizes[key] = size
    blocks.order[key] = stable_order(group, "group")


def _endpoint(graph: GraphState, node_id: str) -> BlockKey:
    group_id = graph.nodes[node_id].subgraph_id
    return BlockKey("group", group_id) if group_id is not None else BlockKey("node", node_id)


def build_blocks(graph: GraphState, scope: LayoutScope) -> LayoutBlocks:
    blocks = LayoutBlocks()
    members: dict[str, list[NodeState]] = defaultdict(list)
    for node in graph.nodes.values():
        if node.subgraph_id is not None:
            members[node.subgraph_id].append(node)
            continue
        key = BlockKey("node", node.id)
        if node.id in scope.node_ids:
            blocks.sizes[key] = Size(NODE_WIDTH, NODE_HEIGHT)
            blocks.order[key] = stable_order(node, "node")
        else:
            position = position_of(node)
            blocks.obstacles.append(Rect(position.x, position.y, NODE_WIDTH, NODE_HEIGHT))
    for group in graph.subgraphs.values():
        if group.id in scope.subgraph_ids:
            _add_group_block(blocks, graph, group, members[group.id])
        else:
            blocks.obstacles.append(group_rect(group, members[group.id]))
    outer_edges = {
        (_endpoint(graph, edge.source), _endpoint(graph, edge.target))
        for edge in graph.edges.values()
    }
    blocks.edges = {
        (source, target)
        for source, target in outer_edges
        if source in blocks.sizes and target in blocks.sizes and source != target
    }
    return blocks
