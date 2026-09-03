from src.modules.pipeline_graph.infra.db_models import GraphEdgeRecord, GraphNodeRecord
from src.node_dsl.core.input_values import (
    NodeInputConstantValue,
    NodeInputExpressionValue,
    NodeInputLinkValue,
)
from src.nodes.tool.conditional_signal_router import ConditionalSignalRouter
from src.pipeline.graph import build_pipeline_from_graph, resolve_execution_target_nodes


def _register_nodes(*node_classes) -> None:
    from src.node_dsl.registry import (
        definitions as definitions_registry,
        hooks as hooks_registry,
        nodes as nodes_registry,
    )

    for node_cls in node_classes:
        if node_cls.__name__ not in nodes_registry.get_all():
            nodes_registry.add(node_cls)
        if node_cls.__name__ not in definitions_registry.NODE_DEFINITIONS:
            definitions_registry.build(node_cls)
        hooks_registry.build(node_cls)


def test_build_pipeline_from_graph_collects_multiple_variable_links():
    user_id = "u1"
    project_id = "p1"

    v1 = GraphNodeRecord(
        ui_id="v1",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="CreateVariable",
        display_name="CreateVariable",
        input_values={},
        store_enabled=False,
        project_id=project_id,
        user_id=user_id,
    )
    v2 = GraphNodeRecord(
        ui_id="v2",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="CreateVariable",
        display_name="CreateVariable",
        input_values={},
        store_enabled=False,
        project_id=project_id,
        user_id=user_id,
    )
    consumer = GraphNodeRecord(
        ui_id="consumer",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="CreateVariable",
        display_name="CreateVariable",
        input_values={},
        store_enabled=False,
        project_id=project_id,
        user_id=user_id,
    )

    e1 = GraphEdgeRecord(
        ui_id="e1",
        type="default",
        source=v1.ui_id,
        source_handle="output-output_variables",
        target=consumer.ui_id,
        target_handle="input-input_variables",
        project_id=project_id,
        user_id=user_id,
    )
    e2 = GraphEdgeRecord(
        ui_id="e2",
        type="default",
        source=v2.ui_id,
        source_handle="output-output_variables",
        target=consumer.ui_id,
        target_handle="input-input_variables",
        project_id=project_id,
        user_id=user_id,
    )

    pipeline = build_pipeline_from_graph(
        nodes=[v1, v2, consumer],
        edges=[e1, e2],
        target_nodes=[consumer.ui_id],
    )

    inputs = pipeline[consumer.ui_id].inputs
    assert isinstance(inputs["input_variables"], list)

    link_values = inputs["input_variables"]
    assert all(isinstance(x, NodeInputLinkValue) for x in link_values)
    assert {(x.node_id, x.output_name) for x in link_values} == {
        ("v1", "output_variables"),
        ("v2", "output_variables"),
    }


def test_build_pipeline_from_graph_collects_multiple_signal_links():
    user_id = "u1"
    project_id = "p1"

    source_a = GraphNodeRecord(
        ui_id="s1",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="CreateVariable",
        display_name="CreateVariable",
        input_values={},
        store_enabled=False,
        project_id=project_id,
        user_id=user_id,
    )
    source_b = GraphNodeRecord(
        ui_id="s2",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="CreateVariable",
        display_name="CreateVariable",
        input_values={},
        store_enabled=False,
        project_id=project_id,
        user_id=user_id,
    )
    target = GraphNodeRecord(
        ui_id="target",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="CreateVariable",
        display_name="CreateVariable",
        input_values={},
        store_enabled=False,
        project_id=project_id,
        user_id=user_id,
    )

    e1 = GraphEdgeRecord(
        ui_id="e-s1",
        type="default",
        source=source_a.ui_id,
        source_handle="output-signal_out",
        target=target.ui_id,
        target_handle="input-signal_in",
        project_id=project_id,
        user_id=user_id,
    )
    e2 = GraphEdgeRecord(
        ui_id="e-s2",
        type="default",
        source=source_b.ui_id,
        source_handle="output-signal_out",
        target=target.ui_id,
        target_handle="input-signal_in",
        project_id=project_id,
        user_id=user_id,
    )

    pipeline = build_pipeline_from_graph(
        nodes=[source_a, source_b, target],
        edges=[e1, e2],
        target_nodes=[target.ui_id],
    )

    signal_input = pipeline[target.ui_id].inputs["signal_in"]
    assert isinstance(signal_input, list)
    assert all(isinstance(x, NodeInputLinkValue) for x in signal_input)
    assert {(x.node_id, x.output_name) for x in signal_input} == {
        ("s1", "signal_out"),
        ("s2", "signal_out"),
    }


def test_build_pipeline_from_graph_supports_structured_const_and_expr_values():
    node = GraphNodeRecord(
        ui_id="node-1",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="SimpleInputNode",
        display_name="SimpleInputNode",
        input_values={
            "const_value": {"__dvt_type": "const", "value": "from_const"},
            "var_value": {"__dvt_type": "expr", "value": "from_project_var", "expression_kind": "single"},
        },
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )

    pipeline = build_pipeline_from_graph(
        nodes=[node],
        edges=[],
        target_nodes=[node.ui_id],
    )

    node_inputs = pipeline[node.ui_id].inputs

    assert isinstance(node_inputs["const_value"], NodeInputConstantValue)
    assert node_inputs["const_value"].value == "from_const"

    assert isinstance(node_inputs["var_value"], NodeInputExpressionValue)
    assert node_inputs["var_value"].value == "from_project_var"


def test_build_pipeline_from_graph_rejects_legacy_scalar_inputs():
    node = GraphNodeRecord(
        ui_id="node-1",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="SimpleInputNode",
        display_name="SimpleInputNode",
        input_values={"raw_value": "legacy"},
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )

    try:
        build_pipeline_from_graph(
            nodes=[node],
            edges=[],
            target_nodes=[node.ui_id],
        )
    except ValueError as exc:
        assert "canonical '__dvt_type'" in str(exc)
    else:
        raise AssertionError("Expected legacy scalar input to be rejected")


def test_build_pipeline_from_graph_service_output_links_to_non_signal_output():
    node = GraphNodeRecord(
        ui_id="node-1",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="CreateVariable",
        display_name="CreateVariable",
        input_values={},
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )

    pipeline = build_pipeline_from_graph(
        nodes=[node],
        edges=[],
        target_nodes=[node.ui_id],
    )

    service_input = pipeline["__service_output__"].inputs["input"]
    assert isinstance(service_input, NodeInputLinkValue)
    assert service_input.node_id == "node-1"
    assert service_input.output_name == "signal_out"


def test_build_pipeline_from_graph_service_output_links_to_signal_output_for_signal_only_nodes():
    node = GraphNodeRecord(
        ui_id="node-1",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="ExecutePython",
        display_name="ExecutePython",
        input_values={},
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )

    pipeline = build_pipeline_from_graph(
        nodes=[node],
        edges=[],
        target_nodes=[node.ui_id],
    )

    service_input = pipeline["__service_output__"].inputs["input"]
    assert isinstance(service_input, NodeInputLinkValue)
    assert service_input.node_id == "node-1"
    assert service_input.output_name == "signal_out"


def test_build_pipeline_from_graph_supports_multiple_target_nodes():
    from src.nodes.testing.simple_input import SimpleInputNode

    _register_nodes(SimpleInputNode)

    node_a = GraphNodeRecord(
        ui_id="node-a",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="SimpleInputNode",
        display_name="SimpleInputNode",
        input_values={"value_in": {"__dvt_type": "const", "value": "a"}},
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )
    node_b = GraphNodeRecord(
        ui_id="node-b",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="SimpleInputNode",
        display_name="SimpleInputNode",
        input_values={"value_in": {"__dvt_type": "const", "value": "b"}},
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )

    pipeline = build_pipeline_from_graph(
        nodes=[node_a, node_b],
        edges=[],
        target_nodes=[node_a.ui_id, node_b.ui_id],
    )

    assert "__service_output_node-a__" in pipeline
    assert "__service_output_node-b__" in pipeline
    assert pipeline["__service_output_node-a__"].inputs["input"].node_id == "node-a"
    assert pipeline["__service_output_node-b__"].inputs["input"].node_id == "node-b"


def test_resolve_execution_target_nodes_uses_service_outputs_for_multiple_targets():
    from src.nodes.testing.simple_input import SimpleInputNode

    _register_nodes(SimpleInputNode)

    node_a = GraphNodeRecord(
        ui_id="node-a",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="SimpleInputNode",
        display_name="SimpleInputNode",
        input_values={"value_in": {"__dvt_type": "const", "value": "a"}},
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )
    node_b = GraphNodeRecord(
        ui_id="node-b",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="SimpleInputNode",
        display_name="SimpleInputNode",
        input_values={"value_in": {"__dvt_type": "const", "value": "b"}},
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )

    target_nodes = [node_a.ui_id, node_b.ui_id]
    pipeline = build_pipeline_from_graph(
        nodes=[node_a, node_b],
        edges=[],
        target_nodes=target_nodes,
    )

    assert resolve_execution_target_nodes(pipeline, target_nodes) == [
        "__service_output_node-a__",
        "__service_output_node-b__",
    ]


def test_build_pipeline_from_graph_wraps_explicit_output_target():
    from src.nodes.testing.simple_output import SimpleOutputNode

    _register_nodes(SimpleOutputNode)

    node = GraphNodeRecord(
        ui_id="output-node",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="SimpleOutputNode",
        display_name="SimpleOutputNode",
        input_values={"value_final": {"__dvt_type": "const", "value": "done"}},
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )

    pipeline = build_pipeline_from_graph(
        nodes=[node],
        edges=[],
        target_nodes=[node.ui_id],
    )

    service_input = pipeline["__service_output__"].inputs["input"]
    assert isinstance(service_input, NodeInputLinkValue)
    assert service_input.node_id == "output-node"
    assert service_input.output_name == "signal_out"
    assert resolve_execution_target_nodes(pipeline, [node.ui_id]) == ["__service_output__"]


def test_build_pipeline_from_graph_without_target_nodes_uses_terminal_nodes():
    from src.nodes.testing.simple_input import SimpleInputNode

    _register_nodes(SimpleInputNode)

    node = GraphNodeRecord(
        ui_id="node-a",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="SimpleInputNode",
        display_name="SimpleInputNode",
        input_values={"value_in": {"__dvt_type": "const", "value": "a"}},
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )

    pipeline = build_pipeline_from_graph(
        nodes=[node],
        edges=[],
    )

    assert "__service_output_node-a__" in pipeline
    assert pipeline["__service_output_node-a__"].inputs["input"].node_id == "node-a"

