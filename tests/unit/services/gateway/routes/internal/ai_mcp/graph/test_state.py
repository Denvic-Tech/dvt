from services.gateway.routes.internal.ai_mcp.graph.mappers import (
    edge_from_ui,
    edge_to_ui,
    node_from_ui,
    node_to_ui,
    subgraph_from_ui,
    subgraph_to_ui,
)
from services.gateway.routes.internal.ai_mcp.graph.state import GraphState

from src.modules.pipeline_graph.infra.schemas import (
    GraphEdgeUISchema,
    GraphNodeUISchema,
    SubgraphUISchema,
)


def test_working_copy_owns_inputs_and_ui_fields_survive_conversion():
    original = GraphNodeUISchema.model_validate(
        {
            "id": "legacy",
            "type": "custom",
            "selected": True,
            "subgraphId": "group",
            "position": {"x": -12.5, "y": 42},
            "data": {
                "name": "JsonToDataFrame",
                "displayName": "Source",
                "comment": "Keep this",
                "storeEnabled": True,
                "showSignalIo": None,
                "showVariablesIo": True,
                "inputValues": {
                    "json": {"__dvt_type": "const", "value": [{"nested": [1, 2]}]},
                    "expression": {
                        "__dvt_type": "expr",
                        "value": "{{ value }}",
                        "expression_kind": "template",
                    },
                },
            },
        }
    )
    state = GraphState(nodes={"legacy": node_from_ui(original)})
    assert node_to_ui(state.nodes["legacy"]).model_dump(mode="json") == original.model_dump(
        mode="json"
    )
    draft = state.working_copy()
    draft.nodes["legacy"].inputs["json"].value[0]["nested"].append(3)
    draft.nodes["legacy"].comment = "Changed"
    assert state.nodes["legacy"].inputs["json"].value == [{"nested": [1, 2]}]
    assert state.nodes["legacy"].comment == "Keep this"


def test_edge_and_group_round_trip_preserves_membership_and_styling():
    edge = GraphEdgeUISchema(
        id="edge",
        type="custom",
        source="a",
        target="b",
        sourceHandle="output-signal",
        targetHandle="input-signal",
        subgraphId="group",
    )
    group = SubgraphUISchema(
        id="group",
        type="subgraph",
        selected=True,
        expanded=False,
        position={"x": 3, "y": 4},
        data={
            "name": "group",
            "displayName": "Visible label",
            "color": "#112233",
            "comment": "Purpose",
        },
    )
    assert edge_to_ui(edge_from_ui(edge)).model_dump(mode="json") == edge.model_dump(mode="json")
    assert subgraph_to_ui(subgraph_from_ui(group)).model_dump(mode="json") == group.model_dump(
        mode="json"
    )
