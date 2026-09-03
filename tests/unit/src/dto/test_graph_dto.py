from src.modules.pipeline_graph.infra.mappers.graph_edges import to_persistent as edge_to_persistent
from src.modules.pipeline_graph.infra.mappers.graph_edges import to_ui as edge_to_ui
from src.modules.pipeline_graph.infra.mappers.graph_nodes import to_persistent as node_to_persistent
from src.modules.pipeline_graph.infra.mappers.graph_nodes import to_ui as node_to_ui
from src.modules.pipeline_graph.infra.mappers.subgraphs import to_persistent as subgraph_to_persistent
from src.modules.pipeline_graph.infra.mappers.subgraphs import to_ui as subgraph_to_ui
from src.modules.pipeline_graph.infra.db_models import (
    GraphEdgeRecord,
    GraphNodeRecord,
    SubgraphRecord,
)
from src.node_dsl.core.input_values import NodeInputConstantValue, parse_node_input_value
from src.modules.pipeline_graph.infra.schemas.graph_edge import GraphEdgeUISchema
from src.modules.pipeline_graph.infra.schemas.graph_node import GraphNodeData, GraphNodeUISchema, Position
from src.modules.pipeline_graph.infra.schemas.subgraph import SubgraphData, SubgraphUISchema


def test_edge_to_ui_maps_fields():
    edge = GraphEdgeRecord(
        ui_id="edge-1",
        type="default",
        subgraph_id="subgraph-1",
        source="node-1",
        source_handle="out-1",
        target="node-2",
        target_handle="in-1",
        project_id="project-1",
        user_id="user-1",
        organization_id="org-1",
    )

    ui = edge_to_ui(edge)

    assert ui == GraphEdgeUISchema(
        id="edge-1",
        type="default",
        subgraphId="subgraph-1",
        source="node-1",
        sourceHandle="out-1",
        target="node-2",
        targetHandle="in-1",
    )


def test_edge_to_persistent_maps_fields():
    ui = GraphEdgeUISchema(
        id="edge-2",
        type="straight",
        subgraphId="subgraph-2",
        source="node-3",
        sourceHandle="out-2",
        target="node-4",
        targetHandle="in-2",
    )

    persistent = edge_to_persistent(
        ui,
        project_id="project-2",
        user_id="user-2",
        organization_id="org-2",
    )

    assert persistent.ui_id == "edge-2"
    assert persistent.type == "straight"
    assert persistent.subgraph_id == "subgraph-2"
    assert persistent.source == "node-3"
    assert persistent.source_handle == "out-2"
    assert persistent.target == "node-4"
    assert persistent.target_handle == "in-2"
    assert persistent.project_id == "project-2"
    assert persistent.user_id == "user-2"
    assert persistent.organization_id == "org-2"


def test_node_to_ui_maps_fields_and_defaults():
    node = GraphNodeRecord(
        ui_id="node-1",
        type="test",
        subgraph_id="subgraph-3",
        position_x=10.0,
        position_y=20.0,
        name="NodeName",
        display_name="Node Display",
        comment=None,
        input_values=None,
        project_id="project-1",
        user_id="user-1",
        organization_id="org-1",
    )

    ui = node_to_ui(node)

    assert ui == GraphNodeUISchema(
        id="node-1",
        type="test",
        subgraphId="subgraph-3",
        position=Position(x=10.0, y=20.0),
        data=GraphNodeData(
            name="NodeName",
            displayName="Node Display",
            showSignalIo=False,
            comment=None,
            inputValues={},
        ),
    )


def test_node_to_persistent_maps_fields():
    ui = GraphNodeUISchema(
        id="node-2",
        type="custom",
        subgraphId="subgraph-4",
        position=Position(x=1.5, y=2.5),
        data=GraphNodeData(
            name="Node2",
            displayName="Node 2",
            showSignalIo=True,
            comment="Note",
            inputValues={"a": {"__dvt_type": "const", "value": 1}},
        ),
    )

    persistent = node_to_persistent(
        ui,
        project_id="project-2",
        user_id="user-2",
        organization_id="org-2",
    )

    assert persistent.ui_id == "node-2"
    assert persistent.type == "custom"
    assert persistent.subgraph_id == "subgraph-4"
    assert persistent.position_x == 1.5
    assert persistent.position_y == 2.5
    assert persistent.name == "Node2"
    assert persistent.display_name == "Node 2"
    assert persistent.show_signal_io is True
    assert persistent.comment == "Note"
    parsed_input = parse_node_input_value(persistent.input_values["a"])
    assert isinstance(parsed_input, NodeInputConstantValue)
    assert parsed_input.value == 1
    assert persistent.project_id == "project-2"
    assert persistent.user_id == "user-2"
    assert persistent.organization_id == "org-2"


def test_subgraph_to_ui_maps_fields():
    subgraph = SubgraphRecord(
        ui_id="subgraph-1",
        type="subgraph",
        position_x=5.0,
        position_y=15.0,
        selected=True,
        name="SubgraphName",
        display_name="SubgraphRecord Display",
        comment="SubgraphRecord comment",
        project_id="project-1",
        user_id="user-1",
        organization_id="org-1",
    )

    ui = subgraph_to_ui(subgraph)

    assert ui == SubgraphUISchema(
        id="subgraph-1",
        type="subgraph",
        position=Position(x=5.0, y=15.0),
        selected=True,
        data=SubgraphData(
            name="SubgraphName",
            displayName="SubgraphRecord Display",
            comment="SubgraphRecord comment",
        ),
    )


def test_subgraph_to_persistent_maps_fields():
    ui = SubgraphUISchema(
        id="subgraph-2",
        type="subgraph",
        position=Position(x=7.5, y=8.5),
        selected=False,
        data=SubgraphData(
            name="Subgraph2",
            displayName="SubgraphRecord 2",
            comment="Comment 2",
        ),
    )

    persistent = subgraph_to_persistent(
        ui,
        project_id="project-2",
        user_id="user-2",
        organization_id="org-2",
    )

    assert persistent.ui_id == "subgraph-2"
    assert persistent.type == "subgraph"
    assert persistent.position_x == 7.5
    assert persistent.position_y == 8.5
    assert persistent.selected is False
    assert persistent.name == "Subgraph2"
    assert persistent.display_name == "SubgraphRecord 2"
    assert persistent.comment == "Comment 2"
    assert persistent.project_id == "project-2"
    assert persistent.user_id == "user-2"
    assert persistent.organization_id == "org-2"
