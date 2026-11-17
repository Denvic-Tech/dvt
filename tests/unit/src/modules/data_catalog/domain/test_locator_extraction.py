from src.modules.data_catalog.domain import (
    DiagnosticReason,
    GraphEdge,
    GraphInputValue,
    GraphNode,
    LinkDirection,
    LocatorKind,
    ProjectGraphSnapshot,
    ProjectStampSource,
)
from src.modules.data_catalog.domain.policies import NODE_LOCATOR_SPECS, extract_locator_candidates

CONNECTION_NODE = GraphNode(
    ui_id="conn",
    name="GetExistDBConnection",
    inputs={"connection_id": GraphInputValue.const("conn-1")},
)


def _connection_edge(target: str) -> GraphEdge:
    return GraphEdge(source="conn", target=target, source_handle="output-connection", target_handle="input-connection")


def _snapshot(*nodes: GraphNode, edges: tuple[GraphEdge, ...] = ()) -> ProjectGraphSnapshot:
    return ProjectGraphSnapshot(
        stamp_source=ProjectStampSource(project_id="p", organization_id="o", graph_revision=1),
        nodes=(CONNECTION_NODE, *nodes),
        edges=edges,
    )


def test_every_spec_node_with_static_connection_becomes_a_candidate():
    nodes = []
    edges = []
    for name, spec in NODE_LOCATOR_SPECS.items():
        if spec.kind is LocatorKind.EXPLICIT:
            inputs = {"table_name": GraphInputValue.const("t")}
        elif spec.kind is LocatorKind.SQL:
            inputs = {"sql_code": GraphInputValue.const("select 1 from t")}
        else:
            inputs = {"manual_variables": GraphInputValue.const({"x": {"table_name": "t"}})}
        nodes.append(GraphNode(ui_id=name, name=name, inputs=inputs))
        edges.append(_connection_edge(name))

    candidates, diagnostics = extract_locator_candidates(_snapshot(*nodes, edges=tuple(edges)))

    assert diagnostics == []
    assert {candidate.node_name for candidate in candidates} == set(NODE_LOCATOR_SPECS)
    assert all(candidate.connection_id == "conn-1" for candidate in candidates)
    by_name = {candidate.node_name: candidate for candidate in candidates}
    assert by_name["WriteDataFrameToDBV4"].direction is LinkDirection.WRITE
    assert by_name["ReadTableFromDBV3"].direction is LinkDirection.READ


def test_mock_connection_and_missing_edge_are_reported_not_registered():
    mock = GraphNode(ui_id="mock", name="GetMockDBConnection")
    reader_from_mock = GraphNode(ui_id="r1", name="ReadTableFromDBV3", inputs={"table_name": GraphInputValue.const("t")})
    reader_without_edge = GraphNode(ui_id="r2", name="ReadTableFromDBV3", inputs={"table_name": GraphInputValue.const("t")})
    snapshot = _snapshot(
        mock,
        reader_from_mock,
        reader_without_edge,
        edges=(GraphEdge(source="mock", target="r1", source_handle="output-connection", target_handle="input-connection"),),
    )

    candidates, diagnostics = extract_locator_candidates(snapshot)

    assert candidates == []
    assert {(item.node_id, item.reason) for item in diagnostics} == {
        ("r1", DiagnosticReason.CONNECTION_NOT_STATIC),
        ("r2", DiagnosticReason.CONNECTION_EDGE_MISSING),
    }


def test_link_and_missing_locator_inputs_are_diagnosed():
    linked = GraphNode(ui_id="l", name="ReadTableFromDBV3", inputs={"table_name": GraphInputValue.link("x", "out")})
    empty = GraphNode(ui_id="e", name="ReadTableFromDBV3", inputs={"table_name": GraphInputValue.const("  ")})
    snapshot = _snapshot(linked, empty, edges=(_connection_edge("l"), _connection_edge("e")))

    candidates, diagnostics = extract_locator_candidates(snapshot)

    assert candidates == []
    assert {(item.node_id, item.reason) for item in diagnostics} == {
        ("l", DiagnosticReason.LINK_INPUT_UNSUPPORTED),
        ("e", DiagnosticReason.LOCATOR_INPUT_MISSING),
    }


def test_expression_inputs_are_kept_for_later_resolution_and_dataframe_inputs_collected():
    writer = GraphNode(
        ui_id="w",
        name="WriteDataFrameToDBV4",
        inputs={"table_name": GraphInputValue.expr("{{ project_variables.t }}", "template")},
    )
    snapshot = _snapshot(
        writer,
        edges=(
            _connection_edge("w"),
            GraphEdge(source="src", target="w", source_handle="output-output", target_handle="input-df"),
        ),
    )

    candidates, _ = extract_locator_candidates(snapshot)

    assert candidates[0].inputs["table_name"].kind == "expr"
    assert candidates[0].dataframe_input_names == frozenset({"df"})


def test_read_variables_sql_mode_requires_sql_code():
    node = GraphNode(
        ui_id="v",
        name="ReadVariablesFromDB",
        inputs={"mode": GraphInputValue.const("sql"), "sql_code": GraphInputValue.const("select 1 from t")},
    )
    candidates, diagnostics = extract_locator_candidates(_snapshot(node, edges=(_connection_edge("v"),)))

    assert diagnostics == []
    assert set(candidates[0].inputs) == {"mode", "sql_code"}
