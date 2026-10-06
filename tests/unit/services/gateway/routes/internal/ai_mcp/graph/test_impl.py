import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.gateway.routes.internal.ai_mcp import router
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError
from services.gateway.routes.internal.ai_mcp.graph import arrangement, impl as graph, preparation
from services.gateway.routes.internal.ai_mcp.graph.layout import LayoutError
from services.gateway.routes.internal.ai_mcp.graph.schemas import GraphPatchSchema
from services.gateway.routes.internal.ai_mcp.graph.snapshot import compute_graph_etag, load_snapshot
from services.gateway.routes.internal.ai_mcp.schemas import ToolCallSchema

from src.crud import graph as graph_crud
from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.node_dsl import get_definition


def chain_patch():
    return {
        "add_nodes": [
            {
                "ref": "source",
                "node_type": "JsonToDataFrame",
                "inputs": {"json": {"kind": "constant", "value": [{"value": 1}]}},
            },
            {"ref": "sink", "node_type": "DataFrameToJson"},
        ],
        "add_connections": [
            {
                "source": {"ref": "source"},
                "source_output": "output",
                "target": {"ref": "sink"},
                "target_input": "df",
            }
        ],
    }


@pytest.fixture
def context(monkeypatch):
    project = SimpleNamespace(
        id="project", user_id="user", organization_id="org", variables={}, graph_revision=0
    )
    principal = SimpleNamespace(user=SimpleNamespace(id="user"), token=SimpleNamespace(id="token"))
    session = AsyncMock()
    monkeypatch.setattr(graph, "get_accessible_project", AsyncMock(return_value=project))
    monkeypatch.setattr(graph_crud, "get_graph_by", AsyncMock(return_value=([], [], [])))
    monkeypatch.setattr(
        preparation,
        "_available_definitions",
        AsyncMock(
            return_value={
                name: get_definition(name) for name in ("JsonToDataFrame", "DataFrameToJson")
            }
        ),
    )
    return session, principal, project


@pytest.mark.asyncio
async def test_validation_preview_and_materialization_have_identical_geometry(context):
    session, principal, project = context
    kwargs = {
        "session": session,
        "principal": principal,
        "project_id": project.id,
        "expected_graph_revision": 0,
        "expected_graph_etag": compute_graph_etag([], [], []),
    }
    result = await graph.validate_graph_changes(**kwargs, patch=chain_patch())
    assert result["valid"] and "preview_graph_etag" not in result
    assert result["preview"]["created_node_refs"] == ["source", "sink"]
    assert result["preview"]["layout"]["moved_nodes"] == [{"ref": "source"}, {"ref": "sink"}]
    assert "__mcp_" not in json.dumps(result)
    session.commit.assert_not_awaited()
    session.execute.assert_not_awaited()
    prepared = []
    for _ in range(2):
        item = await preparation.prepare_patch(
            snapshot=await load_snapshot(session, project),
            session=session,
            principal=principal,
            project=project,
            patch=GraphPatchSchema.model_validate(chain_patch()),
        )
        mapping = item.references.materialize(item.payload)
        positions = {
            ref: next(node.position for node in item.payload.nodes_to_create if node.id == node_id)
            for ref, node_id in mapping.items()
        }
        prepared.append((mapping, positions))
    assert prepared[0][0] != prepared[1][0]
    assert prepared[0][1] == prepared[1][1]


@pytest.mark.asyncio
async def test_validation_reports_missing_input_using_ref(context):
    session, principal, project = context
    patch = chain_patch()
    patch["add_nodes"][0]["inputs"] = {}
    with pytest.raises(AIMCPHTTPError) as error:
        await preparation.prepare_patch(
            snapshot=await load_snapshot(session, project),
            session=session,
            principal=principal,
            project=project,
            patch=GraphPatchSchema.model_validate(patch),
        )
    errors = error.value.detail["details"]["errors"]
    assert any(item.get("node_ref") == "source" for item in errors)
    assert "__mcp_" not in json.dumps(error.value.detail)


@pytest.mark.asyncio
async def test_layout_error_rolls_back_before_any_write(context, monkeypatch):
    session, principal, project = context

    def fail(*args, **kwargs):
        raise LayoutError("Unable to place graph.")

    monkeypatch.setattr(arrangement, "calculate_layout", fail)
    with pytest.raises(AIMCPHTTPError) as error:
        await router.call_tool(
            "apply_graph_changes",
            ToolCallSchema(
                arguments={
                    "project_id": project.id,
                    "expected_graph_revision": 0,
                    "expected_graph_etag": compute_graph_etag([], [], []),
                    "patch": chain_patch(),
                }
            ),
            session,
            principal,
            None,
            None,
        )
    assert error.value.detail["code"] == "GRAPH_LAYOUT_FAILED"
    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_layout_preview_does_not_require_available_node_type(context, monkeypatch):
    session, principal, project = context
    missing = GraphNodeRecord(
        ui_id="legacy",
        type="custom",
        name="UnavailableExtensionNode",
        display_name="Incomplete",
        position_x=100,
        position_y=200,
        project_id="project",
        organization_id="org",
        user_id="user",
    )
    monkeypatch.setattr(graph_crud, "get_graph_by", AsyncMock(return_value=([missing], [], [])))
    preparation._available_definitions.side_effect = AssertionError(
        "Geometry must not inspect catalog"
    )
    result = await router.call_tool(
        "auto_layout_project",
        ToolCallSchema(
            arguments={
                "project_id": project.id,
                "expected_graph_revision": 0,
                "expected_graph_etag": compute_graph_etag([missing], [], []),
            }
        ),
        session,
        principal,
        None,
        None,
    )
    assert result.result["dry_run"]
    assert result.result["moved_node_ids"] == ["legacy"]
    assert (missing.position_x, missing.position_y) == (100, 200)
    session.execute.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        {"position": {"x": 0, "y": 0}},
        {"dry_run": "false"},
        {"session": "forged"},
    ],
)
async def test_layout_rejects_unknown_and_ambiguous_arguments(context, arguments):
    session, principal, project = context
    with pytest.raises(AIMCPHTTPError) as error:
        await router.call_tool(
            "auto_layout_project",
            ToolCallSchema(
                arguments={
                    "project_id": project.id,
                    "expected_graph_revision": 0,
                    "expected_graph_etag": compute_graph_etag([], [], []),
                    **arguments,
                }
            ),
            session,
            principal,
            None,
            None,
        )
    assert error.value.detail["code"] == "INVALID_ARGUMENTS"
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["validate_graph_changes", "apply_graph_changes"])
@pytest.mark.parametrize(
    ("source_output", "target_input", "expected"),
    [
        ("missing", "df", [("UNKNOWN_SOURCE_OUTPUT", "source", "source", "missing")]),
        ("output", "missing", [("UNKNOWN_TARGET_INPUT", "sink", "target", "missing")]),
        (
            "missing",
            "missing",
            [
                ("UNKNOWN_SOURCE_OUTPUT", "source", "source", "missing"),
                ("UNKNOWN_TARGET_INPUT", "sink", "target", "missing"),
            ],
        ),
    ],
)
async def test_unknown_ports_rejected_with_refs_before_writes(
    context, operation, source_output, target_input, expected
):
    session, principal, project = context
    patch = chain_patch()
    # Keep the valid required input, reproducing the silently ignored extra edge.
    patch["add_connections"].append(
        {
            "source": {"ref": "source"},
            "source_output": source_output,
            "target": {"ref": "sink"},
            "target_input": target_input,
        }
    )
    with pytest.raises(AIMCPHTTPError) as error:
        await getattr(graph, operation)(
            session=session,
            principal=principal,
            project_id=project.id,
            expected_graph_revision=0,
            expected_graph_etag=compute_graph_etag([], [], []),
            patch=patch,
        )
    assert error.value.detail["code"] == "GRAPH_VALIDATION_FAILED"
    assert error.value.detail["details"]["errors"] == [
        {
            "code": code,
            "node_ref": ref,
            "connection_index": 1,
            "endpoint": endpoint,
            "port": port,
        }
        for code, ref, endpoint, port in expected
    ]
    assert "__mcp_" not in json.dumps(error.value.detail)
    session.commit.assert_not_awaited()
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_output", "target_input"),
    [
        ("signal_out", "signal_in"),
        ("signal_error", "signal_in"),
        ("output_variables", "input_variables"),
    ],
)
async def test_known_service_ports_remain_valid(context, source_output, target_input):
    session, principal, project = context
    patch = chain_patch()
    patch["add_connections"].append(
        {
            "source": {"ref": "source"},
            "source_output": source_output,
            "target": {"ref": "sink"},
            "target_input": target_input,
        }
    )
    result = await graph.validate_graph_changes(
        session=session,
        principal=principal,
        project_id=project.id,
        expected_graph_revision=0,
        expected_graph_etag=compute_graph_etag([], [], []),
        patch=patch,
    )
    assert result["valid"]


@pytest.mark.asyncio
async def test_existing_source_and_new_target_report_id_and_ref(context, monkeypatch):
    session, principal, project = context
    source = GraphNodeRecord(
        ui_id="existing-source",
        type="custom",
        name="JsonToDataFrame",
        display_name="Source",
        position_x=40,
        position_y=40,
        project_id=project.id,
        organization_id=project.organization_id,
        user_id=project.user_id,
        input_values={"json": {"__dvt_type": "const", "value": []}},
    )
    monkeypatch.setattr(graph_crud, "get_graph_by", AsyncMock(return_value=([source], [], [])))
    patch = chain_patch()
    patch["add_nodes"] = patch["add_nodes"][1:]
    patch["add_connections"][0]["source"] = {"id": source.ui_id}
    patch["add_connections"].append(
        {
            "source": {"id": source.ui_id},
            "source_output": "absent",
            "target": {"ref": "sink"},
            "target_input": "absent",
        }
    )
    with pytest.raises(AIMCPHTTPError) as error:
        await graph.validate_graph_changes(
            session=session,
            principal=principal,
            project_id=project.id,
            expected_graph_revision=0,
            expected_graph_etag=compute_graph_etag([source], [], []),
            patch=patch,
        )
    assert error.value.detail["details"]["errors"] == [
        {
            "code": "UNKNOWN_SOURCE_OUTPUT",
            "node_id": source.ui_id,
            "connection_index": 1,
            "endpoint": "source",
            "port": "absent",
        },
        {
            "code": "UNKNOWN_TARGET_INPUT",
            "node_ref": "sink",
            "connection_index": 1,
            "endpoint": "target",
            "port": "absent",
        },
    ]
