"""Deterministic traversals used by both internal and external layout."""

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite

from ..state import GraphState
from .geometry import LayoutError


@dataclass(frozen=True, order=True)
class BlockKey:
    kind: str
    entity_id: str


@dataclass
class LayoutScope:
    node_ids: set[str]
    subgraph_ids: set[str]


def check_structure(graph: GraphState) -> None:
    for item in [*graph.nodes.values(), *graph.subgraphs.values()]:
        if item.position is not None and not all(
            isfinite(value) for value in (item.position.x, item.position.y)
        ):
            raise LayoutError("Graph positions must be finite.")
    for node in graph.nodes.values():
        if node.subgraph_id is not None and node.subgraph_id not in graph.subgraphs:
            raise LayoutError("A node references a missing subgraph.")
    for edge in graph.edges.values():
        if edge.source not in graph.nodes or edge.target not in graph.nodes:
            raise LayoutError("An edge references a missing node.")
        if edge.subgraph_id is not None and edge.subgraph_id not in graph.subgraphs:
            raise LayoutError("An edge references a missing subgraph.")


def _union_adjacency(before: GraphState, after: GraphState) -> dict[BlockKey, set[BlockKey]]:
    adjacency: dict[BlockKey, set[BlockKey]] = defaultdict(set)
    for graph in (before, after):
        for node in graph.nodes.values():
            key = BlockKey("node", node.id)
            adjacency[key]
            if node.subgraph_id is not None:
                group = BlockKey("group", node.subgraph_id)
                adjacency[key].add(group)
                adjacency[group].add(key)
        for edge in graph.edges.values():
            source = BlockKey("node", edge.source)
            target = BlockKey("node", edge.target)
            adjacency[source].add(target)
            adjacency[target].add(source)
    return adjacency


def _structural_seeds(before: GraphState, after: GraphState) -> set[BlockKey]:
    seeds = set()
    for node_id in before.nodes.keys() | after.nodes.keys():
        old = before.nodes.get(node_id)
        new = after.nodes.get(node_id)
        if old is None or new is None or old.subgraph_id != new.subgraph_id:
            seeds.add(BlockKey("node", node_id))
    for edge_id in before.edges.keys() | after.edges.keys():
        old = before.edges.get(edge_id)
        new = after.edges.get(edge_id)
        if old != new:
            for edge in (old, new):
                if edge is not None:
                    seeds.update((BlockKey("node", edge.source), BlockKey("node", edge.target)))
    return seeds


def affected_scope(before: GraphState, after: GraphState) -> LayoutScope:
    """Closure in the union of old/new graphs, including group membership."""
    adjacency = _union_adjacency(before, after)
    visited = _structural_seeds(before, after)
    queue = deque(sorted(visited))
    while queue:
        for neighbor in sorted(adjacency[queue.popleft()]):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return LayoutScope(
        node_ids={
            key.entity_id for key in visited if key.kind == "node" and key.entity_id in after.nodes
        },
        subgraph_ids={
            key.entity_id
            for key in visited
            if key.kind == "group" and key.entity_id in after.subgraphs
        },
    )


def connected_components[Key: (str, BlockKey)](
    keys: Iterable[Key], edges: set[tuple[Key, Key]]
) -> list[set[Key]]:
    adjacency = {key: set() for key in keys}
    for source, target in edges:
        adjacency[source].add(target)
        adjacency[target].add(source)
    remaining = set(keys)
    result = []
    while remaining:
        start = min(remaining)
        component, queue = {start}, [start]
        remaining.remove(start)
        while queue:
            for neighbor in sorted(adjacency[queue.pop()] & remaining):
                remaining.remove(neighbor)
                component.add(neighbor)
                queue.append(neighbor)
        result.append(component)
    return result


def strong_components[Key: (str, BlockKey)](
    keys: Iterable[Key], edges: set[tuple[Key, Key]]
) -> list[list[Key]]:
    """Iterative Kosaraju avoids recursion limits for long pipelines."""
    outgoing = {key: set() for key in keys}
    incoming = {key: set() for key in keys}
    for source, target in edges:
        outgoing[source].add(target)
        incoming[target].add(source)
    visited, finished = set(), []
    for start in sorted(keys):
        if start in visited:
            continue
        visited.add(start)
        stack = [(start, iter(sorted(outgoing[start])))]
        while stack:
            node, neighbors = stack[-1]
            neighbor = next(neighbors, None)
            if neighbor is None:
                finished.append(node)
                stack.pop()
            elif neighbor not in visited:
                visited.add(neighbor)
                stack.append((neighbor, iter(sorted(outgoing[neighbor]))))
    visited, result = set(), []
    for start in reversed(finished):
        if start in visited:
            continue
        component, stack = [], [start]
        visited.add(start)
        while stack:
            node = stack.pop()
            component.append(node)
            for neighbor in sorted(incoming[node]):
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        result.append(component)
    return result
