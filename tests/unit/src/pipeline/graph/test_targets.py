from src.modules.pipeline_graph.infra.db_models import GraphEdgeRecord, GraphNodeRecord
from src.pipeline.graph import collect_affected_terminal_node_ids


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


def test_collect_affected_terminal_node_ids_returns_union_of_downstream_targets():
    from src.nodes.testing.simple_input import SimpleInputNode

    _register_nodes(SimpleInputNode)

    source = GraphNodeRecord(
        ui_id="source",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="SimpleInputNode",
        display_name="SimpleInputNode",
        input_values={"value_in": {"__dvt_type": "const", "value": "hello"}},
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )
    branch_a = GraphNodeRecord(
        ui_id="branch-a",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="SimpleInputNode",
        display_name="SimpleInputNode",
        input_values={},
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )
    branch_b = GraphNodeRecord(
        ui_id="branch-b",
        type="base",
        position_x=0,
        position_y=0,
        selected=False,
        name="SimpleInputNode",
        display_name="SimpleInputNode",
        input_values={},
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )
    widget = GraphNodeRecord(
        ui_id="widget",
        type="widget",
        position_x=0,
        position_y=0,
        selected=False,
        name="WidgetNode",
        display_name="WidgetNode",
        input_values={},
        store_enabled=False,
        project_id="p1",
        user_id="u1",
    )

    edges = [
        GraphEdgeRecord(
            ui_id="edge-a",
            type="default",
            source=source.ui_id,
            source_handle="output-value_out",
            target=branch_a.ui_id,
            target_handle="input-value_in",
            project_id="p1",
            user_id="u1",
        ),
        GraphEdgeRecord(
            ui_id="edge-b",
            type="default",
            source=source.ui_id,
            source_handle="output-value_out",
            target=branch_b.ui_id,
            target_handle="input-value_in",
            project_id="p1",
            user_id="u1",
        ),
        GraphEdgeRecord(
            ui_id="edge-widget",
            type="default",
            source=branch_a.ui_id,
            source_handle="output-value_out",
            target=widget.ui_id,
            target_handle="input-value_in",
            project_id="p1",
            user_id="u1",
        ),
    ]

    target_node_ids = collect_affected_terminal_node_ids(
        nodes=[source, branch_a, branch_b, widget],
        edges=edges,
        seed_node_ids=[source.ui_id],
    )

    assert target_node_ids == ["branch-b"]
