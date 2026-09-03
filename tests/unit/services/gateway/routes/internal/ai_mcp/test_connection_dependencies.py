from types import SimpleNamespace

from services.gateway.routes.internal.ai_mcp import graph


def _node(value):
    return SimpleNamespace(
        ui_id="node-1",
        name="ConnectionConsumer",
        input_values={"connection": value},
    )


def test_connection_input_names_include_resolved_file_connections() -> None:
    assert "connection" in graph._connection_input_names("LoadCSV")


def test_connection_input_roles_distinguish_object_port_from_id() -> None:
    assert graph._connection_object_input_names("ReadTableFromDBV3") == {"connection"}
    assert graph._connection_object_input_names("GetExistDBConnection") == set()
    assert graph._connection_input_names("GetExistDBConnection") == {"connection_id"}


def test_connection_dependency_analysis_resolves_stored_id(monkeypatch) -> None:
    monkeypatch.setattr(graph, "_connection_input_names", lambda _name: {"connection"})

    connection_ids, unresolved = graph.analyze_graph_connection_dependencies(
        [_node({"__dvt_type": "const", "value": "connection-1"})],
        project_id="project-1",
    )

    assert connection_ids == {"connection-1"}
    assert unresolved == []


def test_connection_dependency_analysis_rejects_id_in_object_port(monkeypatch) -> None:
    monkeypatch.setattr(graph, "_connection_input_names", lambda _name: {"connection"})
    monkeypatch.setattr(graph, "_connection_object_input_names", lambda _name: {"connection"})

    connection_ids, unresolved = graph.analyze_graph_connection_dependencies(
        [_node({"__dvt_type": "const", "value": "connection-1"})],
        project_id="project-1",
    )

    assert connection_ids == set()
    assert unresolved == [{"node_id": "node-1", "input_name": "connection"}]


def test_connection_dependency_analysis_fails_closed_for_expression(monkeypatch) -> None:
    monkeypatch.setattr(graph, "_connection_input_names", lambda _name: {"connection"})

    connection_ids, unresolved = graph.analyze_graph_connection_dependencies(
        [
            _node(
                {
                    "__dvt_type": "expr",
                    "value": "{{ variables.connection_id }}",
                    "expression_kind": "template",
                }
            )
        ],
        project_id="project-1",
    )

    assert connection_ids == set()
    assert unresolved == [{"node_id": "node-1", "input_name": "connection"}]


def test_connection_dependency_analysis_rejects_forged_dvt_reference(monkeypatch) -> None:
    monkeypatch.setattr(graph, "_connection_input_names", lambda _name: {"connection"})
    forged = {
        "id": "dvt-service-files:other-project:node-1:connection",
        "type": "dvt_service_files",
        "properties": {"project_id": "other-project"},
    }

    _, unresolved = graph.analyze_graph_connection_dependencies(
        [_node({"__dvt_type": "const", "value": forged})],
        project_id="project-1",
    )

    assert unresolved == [{"node_id": "node-1", "input_name": "connection"}]


def test_connection_dependency_analysis_accepts_project_local_dvt_reference(monkeypatch) -> None:
    monkeypatch.setattr(graph, "_connection_input_names", lambda _name: {"connection"})
    local = {
        "id": "dvt-service-files:project-1:node-1:connection",
        "type": "dvt_service_files",
        "properties": {
            "project_id": "project-1",
            "root_prefix": "node-inputs/node-1/connection",
        },
    }

    connection_ids, unresolved = graph.analyze_graph_connection_dependencies(
        [_node({"__dvt_type": "const", "value": local})],
        project_id="project-1",
    )

    assert connection_ids == set()
    assert unresolved == []


def test_connection_object_requires_edge_except_existing_project_local_reference() -> None:
    assert graph._connection_object_requires_edge(
        "connection-1",
        optional=False,
        has_incoming_edge=False,
        project_id="project-1",
        node_id="node-1",
        input_name="connection",
        existing_dvt_reference=None,
    )
    assert not graph._connection_object_requires_edge(
        "connection-1",
        optional=False,
        has_incoming_edge=True,
        project_id="project-1",
        node_id="node-1",
        input_name="connection",
        existing_dvt_reference=None,
    )

    local = {
        "id": "dvt-service-files:project-1:node-1:connection",
        "type": "dvt_service_files",
        "properties": {
            "project_id": "project-1",
            "root_prefix": "node-inputs/node-1/connection",
        },
    }
    assert not graph._connection_object_requires_edge(
        local,
        optional=False,
        has_incoming_edge=False,
        project_id="project-1",
        node_id="node-1",
        input_name="connection",
        existing_dvt_reference=local,
    )


def _etag_node(*, x: float = 10.0):
    return SimpleNamespace(
        ui_id="node-1",
        type="custom",
        subgraph_id=None,
        position_x=x,
        position_y=20.0,
        selected=False,
        name="Node",
        display_name="Readable node",
        store_enabled=False,
        show_signal_io=False,
        show_variables_io=False,
        comment="Purpose",
        input_values={"value": {"__dvt_type": "const", "value": 1}},
    )


def test_graph_etag_is_deterministic_and_covers_visual_state() -> None:
    first = graph.compute_graph_etag([_etag_node()], [], [])
    repeated = graph.compute_graph_etag([_etag_node()], [], [])
    moved = graph.compute_graph_etag([_etag_node(x=370.0)], [], [])

    assert first == repeated
    assert moved != first


def test_constant_validation_checks_type_and_bounds() -> None:
    definition = SimpleNamespace(
        optional=False,
        is_list_type=False,
        type="INT",
        options=None,
        min_value=1,
        max_value=10,
    )

    assert graph._constant_validation_error(definition, 5) is None
    assert "incompatible" in graph._constant_validation_error(definition, True)
    assert "below minimum" in graph._constant_validation_error(definition, 0)


def test_variable_constant_accepts_persisted_mapping_default() -> None:
    definition = SimpleNamespace(
        optional=False,
        is_list_type=False,
        type="VARIABLE",
        options=None,
        min_value=None,
        max_value=None,
    )

    assert graph._constant_validation_error(definition, {}) is None
    assert "incompatible" in graph._constant_validation_error(definition, "not-a-map")


def test_incoming_edge_supplies_required_input_instead_of_null_placeholder() -> None:
    definition = SimpleNamespace(
        optional=False,
        is_list_type=False,
        type="DATAFRAME",
        options=None,
        min_value=None,
        max_value=None,
    )

    assert graph._graph_constant_validation_error(
        definition,
        None,
        node_id="filter-node",
        input_name="df",
        incoming_inputs={("filter-node", "df")},
        connection_input_names=set(),
    ) is None
    assert "cannot be null" in graph._graph_constant_validation_error(
        definition,
        None,
        node_id="filter-node",
        input_name="df",
        incoming_inputs=set(),
        connection_input_names=set(),
    )


def test_expression_validation_checks_syntax_and_explicit_project_variables() -> None:
    definition = SimpleNamespace(expression_policy="default")

    valid = graph._expression_validation_error(
        definition,
        expression="project_variables.batch_size + 1",
        expression_kind="single",
        project_variable_names={"batch_size"},
    )
    missing = graph._expression_validation_error(
        definition,
        expression="project_variables.missing + 1",
        expression_kind="single",
        project_variable_names={"batch_size"},
    )

    assert valid is None
    assert "missing" in missing
