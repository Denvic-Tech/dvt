from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa

from services.gateway.routes.internal.ai_mcp.auth import MCPPrincipal
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError
from services.gateway.routes.internal.ai_mcp.graph import impl as graph
from services.gateway.routes.internal.ai_mcp.graph.snapshot import compute_graph_etag

from src.crud import graph as graph_crud
from src.models import OrganizationRecord
from src.modules.ai_mcp_access.domain.entities import MCPToken
from src.modules.ai_mcp_access.domain.types import ResourceScopeMode
from src.modules.ai_mcp_access.domain.value_objects import MCPAccessScope, ResourceScope
from src.modules.pipeline_graph.infra.db_models import (
    GraphEdgeRecord,
    GraphNodeRecord,
    SubgraphRecord,
)
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.user.infra.db_models import UserRecord

pytestmark = [pytest.mark.docker_required, pytest.mark.asyncio(loop_scope="session")]


@pytest_asyncio.fixture(loop_scope="session")
async def context(test_db_async_session):
    session = test_db_async_session
    org = OrganizationRecord(name="MCP graph integration")
    session.add(org)
    await session.flush()
    user = UserRecord(
        email=f"layout-{uuid4()}@example.com",
        hashed_password="unused",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role="admin",
        organization_id=org.id,
    )
    session.add(user)
    await session.flush()
    project = ProjectRecord(name="Layout fixture", user_id=user.id, organization_id=org.id)
    session.add(project)
    await session.flush()
    token = MCPToken(
        id=str(uuid4()),
        user_id=user.id,
        token_digest="unused",
        name="test",
        access_scope=MCPAccessScope(
            projects=ResourceScope(ResourceScopeMode.ALL),
            db_connections=ResourceScope(ResourceScopeMode.ALL),
        ),
        created_at=datetime.now(UTC),
    )
    await session.commit()
    return session, MCPPrincipal(user=user, token=token), project


def row(project, key, *, group=None, x=0, y=0, name="JsonToDataFrame"):
    return GraphNodeRecord(
        ui_id=key,
        type="custom",
        name=name,
        display_name=key,
        position_x=x,
        position_y=y,
        subgraph_id=group,
        project_id=project.id,
        organization_id=project.organization_id,
        user_id=project.user_id,
        input_values={"json": {"__dvt_type": "const", "value": [{"n": 1}]}},
    )


async def snapshot(context):
    session, _, project = context
    return await graph_crud.get_graph_by(session, project_id=project.id)


async def arguments(context):
    session, principal, project = context
    return {
        "session": session,
        "principal": principal,
        "project_id": project.id,
        "expected_graph_revision": project.graph_revision,
        "expected_graph_etag": compute_graph_etag(*await snapshot(context)),
    }


async def task_count(context):
    session, _, project = context
    return await session.scalar(
        sa.select(sa.func.count())
        .select_from(TaskRecord)
        .where(TaskRecord.project_id == project.id)
    )


async def test_geometry_persists_without_task_or_dirty_revision_and_returns_fresh_etag(context):
    session, _, project = context
    group = SubgraphRecord(
        ui_id="g",
        type="subgraph",
        name="g",
        display_name="Group",
        position_x=500,
        position_y=500,
        expanded=True,
        project_id=project.id,
        organization_id=project.organization_id,
        user_id=project.user_id,
    )
    # Unavailable node type deliberately verifies geometry-only behavior.
    member = row(project, "legacy-member", group="g", x=900, y=900, name="Unavailable")
    outside = row(project, "legacy-outside", x=-100, y=-100)
    session.add_all([group, member, outside])
    await session.commit()
    revision, dirty, count = (
        project.graph_revision,
        list(project.dirty_node_ids or []),
        await task_count(context),
    )
    kwargs = await arguments(context)
    preview = await graph.auto_layout_project(**kwargs)
    assert preview["dry_run"] and preview["changes_count"] == 3
    assert (member.position_x, member.position_y) == (900, 900)
    assert (group.position_x, group.position_y) == (500, 500)
    applied = await graph.auto_layout_project(**kwargs, dry_run=False)
    await session.refresh(member)
    await session.refresh(outside)
    await session.refresh(group)
    await session.refresh(project)
    assert (member.position_x, member.position_y) != (900, 900)
    assert (group.position_x, group.position_y) != (500, 500)
    assert project.graph_revision == revision and list(project.dirty_node_ids or []) == dirty
    assert await task_count(context) == count
    assert {n.ui_id for n in (await snapshot(context))[0]} == {"legacy-member", "legacy-outside"}
    assert applied["graph_etag"] == compute_graph_etag(*await snapshot(context))
    assert applied["graph_etag"] != kwargs["expected_graph_etag"]
    with pytest.raises(AIMCPHTTPError) as conflict:
        await graph.auto_layout_project(**kwargs, dry_run=False)
    assert conflict.value.detail["code"] == "GRAPH_ETAG_CONFLICT"


async def test_new_nodes_get_server_ids_validation_does_not_persist_and_stale_apply_fails(context):
    session, _, project = context
    old = row(project, "old-human-id", x=400, y=600)
    session.add(old)
    await session.commit()
    kwargs = await arguments(context)
    patch = {
        "add_nodes": [
            {
                "ref": "old-human-id",
                "node_type": "JsonToDataFrame",
                "inputs": {"json": {"kind": "constant", "value": [{"n": 2}]}},
            }
        ]
    }
    preview = await graph.validate_graph_changes(**kwargs, patch=patch)
    assert preview["valid"]
    assert len((await snapshot(context))[0]) == 1
    applied = await graph.apply_graph_changes(**kwargs, patch=patch)
    created = applied["node_ids_by_ref"]["old-human-id"]
    assert created.startswith("node_") and created != old.ui_id
    nodes, _, _ = await snapshot(context)
    assert {node.ui_id for node in nodes} == {old.ui_id, created}
    assert all(not node.ui_id.startswith("__mcp_") for node in nodes)
    await session.refresh(old)
    assert (old.position_x, old.position_y) == (400, 600)
    assert applied["graph_revision"] == kwargs["expected_graph_revision"] + 1
    with pytest.raises(AIMCPHTTPError) as conflict:
        await graph.apply_graph_changes(**kwargs, patch=patch)
    assert conflict.value.detail["code"] == "GRAPH_REVISION_CONFLICT"
    assert len((await snapshot(context))[0]) == 2


async def test_layout_failure_leaves_nodes_and_geometry_unchanged(context):
    session, _, project = context
    old = row(project, "old", group="missing-group", x=123, y=456)
    session.add(old)
    await session.commit()
    kwargs = await arguments(context)
    patch = {
        "add_nodes": [
            {
                "ref": "new",
                "node_type": "JsonToDataFrame",
                "inputs": {"json": {"kind": "constant", "value": []}},
            }
        ]
    }
    with pytest.raises(AIMCPHTTPError) as error:
        await graph.apply_graph_changes(**kwargs, patch=patch)
    assert error.value.detail["code"] == "GRAPH_LAYOUT_FAILED"
    assert compute_graph_etag(*await snapshot(context)) == kwargs["expected_graph_etag"]
    assert len((await snapshot(context))[0]) == 1


async def test_removing_edge_saves_layout_of_both_components_and_keeps_old_ids(context):
    session, _, project = context
    a, b = row(project, "a"), row(project, "b")
    edge = GraphEdgeRecord(
        ui_id="old-edge",
        type="custom",
        source="a",
        target="b",
        source_handle="output-signal_out",
        target_handle="input-signal_in",
        project_id=project.id,
        organization_id=project.organization_id,
        user_id=project.user_id,
    )
    session.add_all([a, b, edge])
    await session.commit()
    applied = await graph.apply_graph_changes(
        **await arguments(context), patch={"delete_connection_ids": ["old-edge"]}
    )
    await session.refresh(a)
    await session.refresh(b)
    assert a.ui_id == "a" and b.ui_id == "b"
    assert (a.position_x, a.position_y) != (b.position_x, b.position_y)
    assert not (await snapshot(context))[1]
    assert set(applied["nodes_updated"]) == {"b"}  # a already occupies its resulting position
    assert applied["graph_etag"] == compute_graph_etag(*await snapshot(context))
    assert await task_count(context) == 0


async def test_empty_project_and_noop_layout_do_not_touch_project_timestamp(context):
    session, _, project = context
    await session.refresh(project)
    timestamp = project.updated_at
    result = await graph.auto_layout_project(**await arguments(context), dry_run=False)
    assert result["changes_count"] == 0
    await session.refresh(project)
    assert project.updated_at == timestamp
    node = row(project, "already-arranged", x=40, y=40)
    session.add(node)
    await session.commit()
    kwargs = await arguments(context)
    result = await graph.auto_layout_project(**kwargs, dry_run=False)
    assert result["changes_count"] == 0
    assert result["graph_etag"] == kwargs["expected_graph_etag"]
    await session.refresh(project)
    assert project.updated_at == timestamp


@pytest.mark.parametrize(
    ("source_output", "target_input", "expected_codes"),
    [
        ("absent", "df", ["UNKNOWN_SOURCE_OUTPUT"]),
        ("output", "absent", ["UNKNOWN_TARGET_INPUT"]),
        ("absent", "absent", ["UNKNOWN_SOURCE_OUTPUT", "UNKNOWN_TARGET_INPUT"]),
    ],
)
async def test_invalid_ports_do_not_persist_graph_or_create_tasks(
    context, source_output, target_input, expected_codes
):
    session, _, project = context
    source = row(project, "existing-source", x=123, y=456)
    target = row(project, "existing-target", name="DataFrameToJson", x=900, y=456)
    target.input_values = {}
    edge = GraphEdgeRecord(
        ui_id="valid-edge",
        type="custom",
        source=source.ui_id,
        target=target.ui_id,
        source_handle="output-output",
        target_handle="input-df",
        project_id=project.id,
        organization_id=project.organization_id,
        user_id=project.user_id,
    )
    session.add_all([source, target, edge])
    await session.commit()
    kwargs = await arguments(context)
    count = await task_count(context)
    dirty = list(project.dirty_node_ids or [])
    patch = {
        "update_nodes": [{"id": source.ui_id, "comment": "Must not be saved"}],
        "add_nodes": [
            {
                "ref": "new",
                "node_type": "JsonToDataFrame",
                "inputs": {"json": {"kind": "constant", "value": []}},
            }
        ],
        "add_connections": [
            {
                "source": {"id": source.ui_id},
                "source_output": source_output,
                "target": {"id": target.ui_id},
                "target_input": target_input,
            }
        ],
    }
    for handler in (graph.validate_graph_changes, graph.apply_graph_changes):
        with pytest.raises(AIMCPHTTPError) as error:
            await handler(**kwargs, patch=patch)
        assert error.value.detail["code"] == "GRAPH_VALIDATION_FAILED"
        errors = error.value.detail["details"]["errors"]
        assert [item["code"] for item in errors] == expected_codes
        assert all(item["connection_index"] == 0 for item in errors)
        assert {item["node_id"] for item in errors} <= {source.ui_id, target.ui_id}
        # Commit explicitly: an accidentally pending write must not escape the assertions.
        await session.commit()
        await session.refresh(project)
        await session.refresh(source)
        assert source.comment is None
        assert project.graph_revision == kwargs["expected_graph_revision"]
        assert list(project.dirty_node_ids or []) == dirty
        assert compute_graph_etag(*await snapshot(context)) == kwargs["expected_graph_etag"]
        assert await task_count(context) == count


async def test_invalid_existing_edge_is_reported_and_can_be_removed(context):
    session, _, project = context
    source, target = row(project, "source"), row(project, "target", x=500)
    broken = GraphEdgeRecord(
        ui_id="legacy-broken-edge",
        type="custom",
        source=source.ui_id,
        target=target.ui_id,
        source_handle="output-absent",
        target_handle="input-absent",
        project_id=project.id,
        organization_id=project.organization_id,
        user_id=project.user_id,
    )
    session.add_all([source, target, broken])
    await session.commit()
    kwargs = await arguments(context)
    patch = {"update_nodes": [{"id": source.ui_id, "comment": "Unrelated edit"}]}
    for handler in (graph.validate_graph_changes, graph.apply_graph_changes):
        with pytest.raises(AIMCPHTTPError) as error:
            await handler(**kwargs, patch=patch)
        assert error.value.detail["details"]["errors"] == [
            {
                "code": "UNKNOWN_SOURCE_OUTPUT",
                "node_id": source.ui_id,
                "connection_id": broken.ui_id,
                "endpoint": "source",
                "port": "absent",
            },
            {
                "code": "UNKNOWN_TARGET_INPUT",
                "node_id": target.ui_id,
                "connection_id": broken.ui_id,
                "endpoint": "target",
                "port": "absent",
            },
        ]
    assert compute_graph_etag(*await snapshot(context)) == kwargs["expected_graph_etag"]
    assert await task_count(context) == 0

    repair = {"delete_connection_ids": [broken.ui_id]}
    assert (await graph.validate_graph_changes(**kwargs, patch=repair))["valid"]
    applied = await graph.apply_graph_changes(**kwargs, patch=repair)
    assert applied["edges_deleted"] == [broken.ui_id]
    assert not (await snapshot(context))[1]
    assert {node.ui_id for node in (await snapshot(context))[0]} == {"source", "target"}
