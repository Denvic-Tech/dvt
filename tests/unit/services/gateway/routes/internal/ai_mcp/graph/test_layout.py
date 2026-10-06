from copy import deepcopy
from time import perf_counter

import pytest

from services.gateway.routes.internal.ai_mcp.graph.layout import LayoutError, calculate_layout
from services.gateway.routes.internal.ai_mcp.graph.layout.geometry import (
    NODE_HEIGHT,
    NODE_WIDTH,
    Rect,
)
from services.gateway.routes.internal.ai_mcp.graph.state import (
    EdgeState,
    GraphState,
    NodeState,
    Position,
    SubgraphState,
)


def layout(nodes, connections, groups, *, before_nodes=None, before_edges=None, full=False):
    before = (
        GraphState(before_nodes or {}, before_edges or {}, groups)
        if before_nodes is not None
        else None
    )
    return calculate_layout(GraphState(nodes, connections, groups), before=before, full=full)


def node(key, x=0, y=0, group=None):
    return NodeState(id=key, position=Position(x, y), subgraph_id=group)


def group(key, expanded=True):
    return SubgraphState(id=key, position=Position(0, 0), expanded=expanded)


def edges(*pairs):
    return {f"e{i}": EdgeState(f"e{i}", source, target) for i, (source, target) in enumerate(pairs)}


def assert_no_overlap(positions):
    rects = [Rect(p.x, p.y, NODE_WIDTH, NODE_HEIGHT) for p in positions.values()]
    assert all(not a.intersects(b) for i, a in enumerate(rects) for b in rects[i + 1 :])


def test_branch_merge_layers_are_readable_and_deterministic():
    nodes = {key: node(key) for key in "abcd"}
    connections = edges(("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"))
    result = layout(nodes, connections, {}, full=True)
    assert result == layout(dict(reversed(list(nodes.items()))), connections, {}, full=True)
    p = result.node_positions
    assert p["a"].x < p["b"].x == p["c"].x < p["d"].x
    assert p["b"].y != p["c"].y
    assert_no_overlap(p)
    assert nodes["a"].position == Position(0, 0)


def test_insertion_rearranges_chain_but_does_not_touch_independent_node():
    before = {"a": node("a", 50, 60), "b": node("b", 500, 60), "other": node("other", 40, 0)}
    nodes = {**before, "inserted": node("inserted")}
    result = layout(
        nodes,
        edges(("a", "inserted"), ("inserted", "b")),
        {},
        before_nodes=before,
        before_edges=edges(("a", "b")),
    )
    assert set(result.node_positions) == {"a", "b", "inserted"}
    assert result.node_positions["a"].x < result.node_positions["inserted"].x
    assert result.node_positions["inserted"].x < result.node_positions["b"].x
    assert_no_overlap({**result.node_positions, "other": before["other"].position})


@pytest.mark.parametrize("delete_node", [False, True])
def test_removal_keeps_both_surviving_components_in_scope(delete_node):
    before = {key: node(key) for key in "abcd"}
    old_edges = edges(("a", "b"), ("b", "c"))
    nodes = {key: value for key, value in before.items() if key != "b" or not delete_node}
    new_edges = {} if delete_node else {"e0": old_edges["e0"]}
    result = layout(nodes, new_edges, {}, before_nodes=before, before_edges=old_edges)
    assert set(result.node_positions) == ({"a", "c"} if delete_node else {"a", "b", "c"})
    assert_no_overlap(result.node_positions)


def test_new_independent_node_is_below_unchanged_graph():
    before = {"old": node("old", 40, 500)}
    result = layout({**before, "new": node("new")}, {}, {}, before_nodes=before)
    assert set(result.node_positions) == {"new"}
    assert result.node_positions["new"].y >= 500 + NODE_HEIGHT + 120


def test_parameter_only_change_preserves_every_position():
    before = {"a": node("a", 123, 456)}
    nodes = deepcopy(before)
    nodes["a"].comment = "Updated"
    result = layout(nodes, {}, {}, before_nodes=before)
    assert not result.node_positions
    assert not result.subgraph_positions


@pytest.mark.parametrize("expanded", [True, False])
def test_group_closure_includes_unconnected_members_and_external_neighbors(expanded):
    before = {
        "a": node("a", group="g"),
        "b": node("b", group="g"),
        "outside": node("outside"),
        "untouched": node("untouched", 0, 5000),
    }
    old_edges = edges(("b", "outside"))
    nodes = {**before, "new": node("new", group="g")}
    result = layout(
        nodes, old_edges, {"g": group("g", expanded)}, before_nodes=before, before_edges=old_edges
    )
    assert set(result.node_positions) == {"a", "b", "new", "outside"}
    assert set(result.subgraph_positions) == {"g"}
    assert_no_overlap({key: result.node_positions[key] for key in ("a", "b", "new")})
    assert result.node_positions["a"].x >= result.subgraph_positions["g"].x + 80


def test_moving_membership_relayouts_both_groups():
    before = {
        "a": node("a", group="left"),
        "b": node("b", group="left"),
        "c": node("c", group="right"),
    }
    nodes = deepcopy(before)
    nodes["a"].subgraph_id = "right"
    result = layout(nodes, {}, {key: group(key) for key in ("left", "right")}, before_nodes=before)
    assert set(result.node_positions) == set(nodes)
    assert set(result.subgraph_positions) == {"left", "right"}


def test_cycles_and_cycles_created_by_group_contraction():
    nodes = {"a": node("a", group="g"), "b": node("b"), "c": node("c", group="g")}
    result = layout(nodes, edges(("a", "b"), ("b", "c")), {"g": group("g")}, full=True)
    assert_no_overlap(result.node_positions)
    plain = {key: node(key) for key in "abc"}
    result = layout(plain, edges(("a", "b"), ("b", "a"), ("b", "c")), {}, full=True)
    p = result.node_positions
    assert p["a"].x == p["b"].x < p["c"].x
    assert_no_overlap(p)


def test_empty_graph_and_empty_subgraph():
    assert layout({}, {}, {}, full=True).bounds == Rect(0, 0, 0, 0)
    result = layout({}, {}, {"g": group("g")}, full=True)
    assert result.subgraph_positions == {"g": Position(40, 40)}


@pytest.mark.parametrize(
    "nodes,connections,groups",
    [
        ({"a": node("a")}, edges(("a", "missing")), {}),
        ({"a": node("a", group="missing")}, {}, {}),
        ({"a": node("a", float("nan"))}, {}, {}),
        ({"a": node("a")}, {"e": EdgeState("e", "a", "a", subgraph_id="missing")}, {}),
    ],
)
def test_corrupt_structure_and_nonfinite_positions_fail(nodes, connections, groups):
    with pytest.raises(LayoutError):
        layout(nodes, connections, groups, full=True)


@pytest.mark.parametrize("count", [100, 500])
def test_large_branched_graph_performance(count):
    nodes = {f"n{i:04}": node(f"n{i:04}") for i in range(count)}
    pairs = [
        (f"n{i:04}", f"n{j:04}") for i in range(count) for j in range(i + 1, min(i + 5, count))
    ]
    connections = edges(*pairs)
    started = perf_counter()
    result = layout(nodes, connections, {}, full=True)
    elapsed = perf_counter() - started
    print(f"layout: nodes={count}, edges={len(connections)}, seconds={elapsed:.4f}")
    assert len(result.node_positions) == count
    assert_no_overlap(result.node_positions)


def test_large_grouped_graph():
    nodes = {f"n{i:04}": node(f"n{i:04}", group=f"g{i // 25}") for i in range(500)}
    groups = {f"g{i}": group(f"g{i}", expanded=i % 2 == 0) for i in range(20)}
    connections = edges(*[(f"n{i:04}", f"n{i + 1:04}") for i in range(499)])
    started = perf_counter()
    result = layout(nodes, connections, groups, full=True)
    print(f"grouped layout: nodes=500, seconds={perf_counter() - started:.4f}")
    assert len(result.node_positions) == 500
    assert len(result.subgraph_positions) == 20
