"""SCC condensation, directional layers, barycenter ordering and local geometry."""

from collections import defaultdict, deque
from dataclasses import dataclass
from functools import partial

from .geometry import (
    COMPONENT_GAP,
    LAYER_GAP,
    NODE_GAP,
    OrderKey,
    Placement,
    Rect,
    Size,
    bounding_rect,
)
from .topology import BlockKey, connected_components, strong_components


@dataclass
class CondensedGraph[Key]:
    members: dict[int, list[Key]]
    outgoing: dict[int, set[int]]
    incoming: dict[int, set[int]]
    order: dict[int, OrderKey]


def condense_cycles[Key: (str, BlockKey)](
    sizes: dict[Key, Size],
    edges: set[tuple[Key, Key]],
    order: dict[Key, OrderKey],
) -> CondensedGraph[Key]:
    components = strong_components(sizes, edges)
    members = {
        index: sorted(items, key=order.__getitem__) for index, items in enumerate(components)
    }
    owner = {key: index for index, items in members.items() for key in items}
    graph = CondensedGraph(
        members=members,
        outgoing={index: set() for index in members},
        incoming={index: set() for index in members},
        order={index: min(order[key] for key in items) for index, items in members.items()},
    )
    for source, target in edges:
        source_component = owner[source]
        target_component = owner[target]
        if source_component != target_component:
            graph.outgoing[source_component].add(target_component)
            graph.incoming[target_component].add(source_component)
    return graph


def assign_layers[Key: (str, BlockKey)](graph: CondensedGraph[Key]) -> dict[int, list[int]]:
    degrees = {key: len(value) for key, value in graph.incoming.items()}
    queue = deque(
        sorted(
            (key for key, degree in degrees.items() if degree == 0),
            key=graph.order.__getitem__,
        )
    )
    layer_by_component = dict.fromkeys(degrees, 0)
    while queue:
        source = queue.popleft()
        for target in sorted(graph.outgoing[source], key=graph.order.__getitem__):
            layer_by_component[target] = max(
                layer_by_component[target],
                layer_by_component[source] + 1,
            )
            degrees[target] -= 1
            if degrees[target] == 0:
                queue.append(target)
    layers: dict[int, list[int]] = defaultdict(list)
    for component, layer in layer_by_component.items():
        layers[layer].append(component)
    for components in layers.values():
        components.sort(key=graph.order.__getitem__)
    return layers


def _barycenter_order(
    component: int,
    *,
    neighbors: dict[int, set[int]],
    positions: dict[int, int],
    order: dict[int, OrderKey],
) -> tuple[float, int, OrderKey]:
    adjacent = neighbors[component]
    center = (
        sum(positions[key] for key in sorted(adjacent)) / len(adjacent)
        if adjacent
        else positions[component]
    )
    return center, positions[component], order[component]


def order_layers[Key: (str, BlockKey)](
    layers: dict[int, list[int]], graph: CondensedGraph[Key]
) -> None:
    """Four alternating sweeps; previous rank and original order break ties."""
    for sweep in range(4):
        positions = {
            component: index
            for components in layers.values()
            for index, component in enumerate(components)
        }
        forward = sweep % 2 == 0
        neighbors = graph.incoming if forward else graph.outgoing
        for layer in sorted(layers, reverse=not forward):
            layers[layer].sort(
                key=partial(
                    _barycenter_order,
                    neighbors=neighbors,
                    positions=positions,
                    order=graph.order,
                )
            )
            positions.update({component: index for index, component in enumerate(layers[layer])})


def place_layers[Key: (str, BlockKey)](
    sizes: dict[Key, Size],
    layers: dict[int, list[int]],
    graph: CondensedGraph[Key],
) -> Placement[Key]:
    rectangles: dict[Key, Rect] = {}
    x = 0.0
    for layer in sorted(layers):
        y = 0.0
        for component in layers[layer]:
            for key in graph.members[component]:
                size = sizes[key]
                rectangles[key] = Rect(x, y, size.width, size.height)
                y += size.height + NODE_GAP
        layer_width = max(
            sizes[key].width for component in layers[layer] for key in graph.members[component]
        )
        x += layer_width + LAYER_GAP
    return Placement(rectangles, bounding_rect(rectangles.values()))


def layered_layout[Key: (str, BlockKey)](
    sizes: dict[Key, Size],
    edges: set[tuple[Key, Key]],
    order: dict[Key, OrderKey],
) -> Placement[Key]:
    if not sizes:
        return Placement({}, Rect(0, 0, 0, 0))
    graph = condense_cycles(sizes, edges, order)
    layers = assign_layers(graph)
    order_layers(layers, graph)
    return place_layers(sizes, layers, graph)


def pack_components[Key: (str, BlockKey)](
    sizes: dict[Key, Size],
    edges: set[tuple[Key, Key]],
    order: dict[Key, OrderKey],
) -> Placement[Key]:
    rectangles: dict[Key, Rect] = {}
    y = 0.0
    components = sorted(
        connected_components(sizes, edges),
        key=lambda items: min(order[key] for key in items),
    )
    for component in components:
        selected_edges = {
            (source, target)
            for source, target in edges
            if source in component and target in component
        }
        placement = layered_layout(
            {key: sizes[key] for key in component},
            selected_edges,
            order,
        )
        rectangles.update(
            {key: rect.translated(0, y) for key, rect in placement.rectangles.items()}
        )
        y += placement.bounds.height + COMPONENT_GAP
    return Placement(rectangles, bounding_rect(rectangles.values()))
