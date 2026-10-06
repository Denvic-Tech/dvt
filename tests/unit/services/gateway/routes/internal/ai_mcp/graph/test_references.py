import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from services.dvt_ai_mcp.models import GraphPatch
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError
from services.gateway.routes.internal.ai_mcp.graph.references import resolve_patch
from services.gateway.routes.internal.ai_mcp.graph.schemas import GraphPatchSchema
from services.gateway.routes.project.graph.graph_operations import GraphOperationsAggregated


@pytest.mark.parametrize("model", [GraphPatch, GraphPatchSchema])
@pytest.mark.parametrize(
    "patch",
    [
        {"add_nodes": [{"id": "old", "node_type": "N"}]},
        {"add_nodes": [{"ref": " ", "node_type": "N"}]},
        {"add_nodes": [{"ref": "a", "node_type": "N", "position": {"x": 0, "y": 0}}]},
        {"update_nodes": [{"id": "a", "position": None}]},
        {
            "add_connections": [
                {"source": "a", "target": "b", "source_output": "x", "target_input": "x"}
            ]
        },
        {
            "add_connections": [
                {
                    "source": {"id": "a", "ref": "b"},
                    "target": {"ref": "c"},
                    "source_output": "x",
                    "target_input": "x",
                }
            ]
        },
        {
            "add_connections": [
                {
                    "id": "edge",
                    "source": {"id": "a"},
                    "target": {"ref": "c"},
                    "source_output": "x",
                    "target_input": "x",
                }
            ]
        },
        {
            "add_connections": [
                {
                    "source": {"ref": ""},
                    "target": {"id": "a"},
                    "source_output": "x",
                    "target_input": "x",
                }
            ]
        },
        {"unexpected": []},
    ],
)
def test_strict_contract_on_both_boundaries(model, patch):
    with pytest.raises(ValidationError):
        model.model_validate(patch)


def test_refs_and_existing_ids_do_not_collide_or_rewrite_values():
    patch = GraphPatchSchema.model_validate(
        {
            "add_nodes": [
                {
                    "ref": "same",
                    "node_type": "N",
                    "inputs": {"value": {"kind": "constant", "value": "same"}},
                }
            ],
            "add_connections": [
                {
                    "source": {"id": "same"},
                    "target": {"ref": "same"},
                    "source_output": "out",
                    "target_input": "in",
                }
            ],
        }
    )
    resolved = resolve_patch(patch, {"same", "__mcp_node_00000000__"}, set())
    added = resolved.add_nodes[0]
    assert added.id not in {"same", "__mcp_node_00000000__"}
    assert added.inputs["value"].value == "same"
    edge = resolved.add_connections[0]
    assert edge.source == "same" and edge.target == added.id
    assert resolved.node_reference(added.id) == {"ref": "same"}


@pytest.mark.parametrize(
    "patch,code",
    [
        ({"add_nodes": [{"ref": "x", "node_type": "N"}] * 2}, "DUPLICATE_NODE_REF"),
        (
            {
                "add_connections": [
                    {
                        "source": {"ref": "unknown"},
                        "target": {"id": "existing"},
                        "source_output": "out",
                        "target_input": "in",
                    }
                ]
            },
            "UNKNOWN_NODE_REF",
        ),
        (
            {
                "delete_node_ids": ["existing"],
                "add_connections": [
                    {
                        "source": {"id": "existing"},
                        "target": {"id": "existing"},
                        "source_output": "out",
                        "target_input": "in",
                    }
                ],
            },
            "UNKNOWN_CONNECTION_NODE",
        ),
    ],
)
def test_bad_references_are_structured_errors(patch, code):
    with pytest.raises(AIMCPHTTPError) as error:
        resolve_patch(GraphPatchSchema.model_validate(patch), {"existing"}, set())
    assert error.value.detail["code"] == "GRAPH_VALIDATION_FAILED"
    assert error.value.detail["details"]["errors"][0]["code"] == code


def test_materialization_only_changes_graph_identity_and_diagnostics_expose_refs():
    patch = GraphPatchSchema.model_validate(
        {
            "add_nodes": [{"ref": "new", "node_type": "N"}],
            "add_connections": [
                {
                    "source": {"id": "existing"},
                    "target": {"ref": "new"},
                    "source_output": "out",
                    "target_input": "in",
                }
            ],
        }
    )
    resolved = resolve_patch(patch, {"existing"}, set())
    temporary = resolved.node_ids_by_ref["new"]
    edge = resolved.add_connections[0]
    payload = GraphOperationsAggregated.model_validate(
        {
            "nodes_to_create": [
                {
                    "id": temporary,
                    "type": "custom",
                    "position": {"x": 1, "y": 2},
                    "data": {
                        "name": "N",
                        "displayName": "N",
                        "inputValues": {"value": {"__dvt_type": "const", "value": "new"}},
                    },
                }
            ],
            "edges_to_create": [
                {
                    "id": edge.id,
                    "type": "custom",
                    "source": "existing",
                    "target": temporary,
                    "sourceHandle": "output-out",
                    "targetHandle": "input-in",
                }
            ],
        }
    )
    diagnostics = resolved.diagnostics(
        {
            "node_id": temporary,
            "node_ids": [temporary, "existing"],
            "connection_id": edge.id,
            "message": f"Bad {temporary}",
        }
    )
    assert diagnostics["node_ref"] == "new"
    assert diagnostics["nodes"] == [{"ref": "new"}, {"id": "existing"}]
    assert diagnostics["connection_index"] == 0
    assert "__mcp_" not in json.dumps(diagnostics)
    mapping = resolved.materialize(payload)
    assert mapping["new"].startswith("node_")
    UUID(mapping["new"].removeprefix("node_"))
    assert payload.nodes_to_create[0].id == mapping["new"]
    assert payload.edges_to_create[0].target == mapping["new"]
    assert payload.edges_to_create[0].source == "existing"
    UUID(payload.edges_to_create[0].id.removeprefix("edge_"))
    assert payload.nodes_to_create[0].data.inputValues["value"].value == "new"
