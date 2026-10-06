from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from db_connection import AccessDeniedError

from services.gateway.routes.internal.ai_mcp import access, context, data, router, tasks
from services.gateway.routes.internal.ai_mcp.auth import MCPPrincipal
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError
from services.gateway.routes.internal.ai_mcp.graph import impl as graph, preparation
from services.gateway.routes.internal.ai_mcp.graph.connections import (
    analyze_graph_connection_dependencies,
)
from services.gateway.routes.internal.ai_mcp.graph.schemas import GraphPatchSchema
from services.gateway.routes.internal.ai_mcp.graph.snapshot import compute_graph_etag, load_snapshot
from services.gateway.routes.internal.ai_mcp.schemas import ToolCallSchema

from src.crud import graph as graph_crud
from src.modules.ai_mcp_access.domain import MCPAccessScope, ResourceScope, ResourceScopeMode
from src.modules.pipeline_graph.infra.mappers import (
    graph_edges as graph_edges_dto,
    graph_nodes as graph_nodes_dto,
)

KAFKA_NODES = {"GetExistKafkaConnection", "ReadKafkaMessages", "CommitKafkaOffsets"}


def principal(ids=("kafka",)):
    return MCPPrincipal(
        user=SimpleNamespace(id="user", organization_id="org"),
        token=SimpleNamespace(
            id="token",
            access_scope=MCPAccessScope(
                projects=ResourceScope(ResourceScopeMode.ALL),
                db_connections=ResourceScope(ResourceScopeMode.SELECTED, frozenset(ids)),
            ),
        ),
    )


def connection(id="kafka", type="kafka", kind="queue"):
    return SimpleNamespace(
        id=id,
        name=id,
        kind=kind,
        type=type,
        driver=None,
        deleted_at=None,
        properties={
            "bootstrap_servers": ["localhost:9092"],
            "ssl_ca_pem": "private-ca",
            "nested": {"password": "hidden", "ssl_ca_pem": "nested-ca"},
        },
        labels={},
        metadata={},
        updated_at=datetime.now(UTC),
    )


async def call(tool, who=None, **arguments):
    result = await router.call_tool(
        tool,
        ToolCallSchema(arguments=arguments),
        AsyncMock(),
        who or principal(),
        None,
        None,
    )
    return result.result


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setattr(context, "_ready_extensions", AsyncMock(return_value=set()))
    service = SimpleNamespace(
        list=AsyncMock(
            return_value=[
                connection(),
                connection("other"),
                connection("redis", "redis"),
                connection("sql", "postgres", "sql"),
            ]
        ),
        get=AsyncMock(return_value=connection()),
    )
    monkeypatch.setattr(data, "get_connection_service", lambda: service)
    monkeypatch.setattr(access, "get_connection_service", lambda: service)
    monkeypatch.setattr(data, "list_accessible_projects", AsyncMock(return_value=[]))
    return service


@pytest.mark.asyncio
async def test_kafka_definitions_docs_and_schemas_are_stable(catalog):
    result = await call("search_nodes", query="kafka")
    assert {item["name"] for item in result["items"]} == KAFKA_NODES
    definitions = {}
    for name in KAFKA_NODES:
        for locale in ("en", "ru"):
            definition = await call("get_node_definition", node_name=name, locale=locale)
            assert definition["documentation_available"]
            assert definition["visible"] and not definition["experimental"]
            definitions[name] = definition
    assert (
        definitions["GetExistKafkaConnection"]["input_definitions"]["connection_id"]["type"]
        == "KAFKA_CONNECTION_ID"
    )
    read = definitions["ReadKafkaMessages"]["input_definitions"]
    assert read["partitions"]["is_list_type"]
    assert read["start_offsets"]["type"] == "JSON"
    assert read["start_mode"]["default"] == "committed"
    assert read["key_format"]["default"] == "binary"
    assert read["value_format"]["default"] == "text"
    assert definitions["CommitKafkaOffsets"]["input_definitions"]["offsets"]["type"] == "JSON"
    with pytest.raises(AIMCPHTTPError):
        await call("get_node_definition", node_name="ReadQueueTopic")


@pytest.mark.asyncio
async def test_connections_keep_scope_actor_and_redact_ca(catalog):
    who = principal(("kafka", "redis", "sql"))
    result = await call("list_connections", who)
    assert {item["id"] for item in result["items"]} == {"kafka", "sql"}
    assert catalog.list.call_args.kwargs["actor"] is who.user
    item = await call("get_connection", who, connection_id="kafka")
    assert item["properties"] == {"bootstrap_servers": ["localhost:9092"], "nested": {}}
    assert not any(item["capabilities"].values())
    assert catalog.get.call_args.kwargs["actor"] is who.user
    catalog.get.reset_mock()
    with pytest.raises(AIMCPHTTPError):
        await call("get_connection", who, connection_id="other")
    catalog.get.assert_not_awaited()
    # The connection service owns user/organization ACL. Its denial must not be bypassed.
    catalog.get.side_effect = AccessDeniedError("private backend detail")
    with pytest.raises(AIMCPHTTPError) as error:
        await call("get_connection", who, connection_id="kafka")
    assert error.value.detail["code"] == "CONNECTION_NOT_FOUND_OR_DENIED"
    assert "private" not in str(error.value.detail)


def kafka_patch():
    def constant(value):
        return {"kind": "constant", "value": value}

    return {
        "add_nodes": [
            {
                "ref": "connection",
                "node_type": "GetExistKafkaConnection",
                "inputs": {"connection_id": {"kind": "connection_ref", "connection_id": "kafka"}},
            },
            {
                "ref": "read",
                "node_type": "ReadKafkaMessages",
                "inputs": {
                    "topic": constant("orders"),
                    "group_id": constant("acceptance"),
                    "partitions": constant([0, 1]),
                    "start_mode": constant("explicit"),
                    "start_offsets": constant({"0": 0, "1": 0}),
                    "max_messages": constant(3),
                    "key_format": constant("binary"),
                    "value_format": constant("text"),
                },
            },
            {
                "ref": "commit",
                "node_type": "CommitKafkaOffsets",
                "inputs": {"offsets": {"kind": "expression", "value": "kafka_offsets"}},
            },
        ],
        "add_connections": [
            {
                "source": {"ref": "connection"},
                "source_output": "connection",
                "target": {"ref": target},
                "target_input": "connection",
            }
            for target in ("read", "commit")
        ]
        + [
            {
                "source": {"ref": "read"},
                "source_output": "output_variables",
                "target": {"ref": "commit"},
                "target_input": "input_variables",
            }
        ],
    }


@pytest.mark.asyncio
async def test_graph_connection_ref_validation_and_execution_scope(catalog, monkeypatch):
    project = SimpleNamespace(
        id="project", user_id="user", organization_id="org", variables={}, graph_revision=0
    )
    monkeypatch.setattr(graph_crud, "get_graph_by", AsyncMock(return_value=([], [], [])))
    monkeypatch.setattr(graph, "get_accessible_project", AsyncMock(return_value=project))
    patch = kafka_patch()
    validated = await call(
        "validate_graph_changes",
        project_id=project.id,
        expected_graph_revision=0,
        expected_graph_etag=compute_graph_etag([], [], []),
        patch=patch,
    )
    assert validated["valid"]
    prepared = await preparation.prepare_patch(
        snapshot=await load_snapshot(AsyncMock(), project),
        session=AsyncMock(),
        principal=principal(),
        project=project,
        patch=GraphPatchSchema.model_validate(patch),
    )
    nodes = [
        graph_nodes_dto.to_persistent(node, project.id, "user", "org")
        for node in prepared.payload.nodes_to_create
    ]
    edges = [
        graph_edges_dto.to_persistent(edge, project.id, "user", "org")
        for edge in prepared.payload.edges_to_create
    ]
    ids, unresolved = analyze_graph_connection_dependencies(nodes, project_id=project.id)
    assert ids == {"kafka"} and not unresolved
    monkeypatch.setattr(
        tasks.graph_crud, "get_graph_by", AsyncMock(return_value=(nodes, edges, []))
    )
    monkeypatch.setattr(tasks, "get_accessible_project", AsyncMock(return_value=project))
    dispatch = AsyncMock(return_value=SimpleNamespace(task_id="accepted-task"))
    monkeypatch.setattr(tasks.task_impl, "create_task_route_impl", dispatch)
    result = await call("run_project", project_id=project.id)
    assert result["task_id"] == "accepted-task"
    dispatch.reset_mock()
    with pytest.raises(AIMCPHTTPError):
        await call("run_project", principal(()), project_id=project.id)
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_graph_persists_kafka_nodes_and_reference(
    catalog,
    monkeypatch,
    async_db_session,
    test_user_project,
    test_user,
    test_organization,
):
    from services.gateway.routes.project.graph import graph_operations

    # Sync fixture records live in a different SQLite database.
    await async_db_session.merge(test_organization)
    user = await async_db_session.merge(test_user)
    project = await async_db_session.merge(test_user_project)
    await async_db_session.commit()
    initial_revision = project.graph_revision
    who = MCPPrincipal(user=user, token=principal().token)
    enqueue = AsyncMock(return_value=SimpleNamespace(task_id="metadata-task"))
    monkeypatch.setattr(graph_operations, "enqueue_task_from_project", enqueue)
    before = await graph_crud.get_graph_by(
        async_db_session,
        project_id=test_user_project.id,
    )
    result = await router.call_tool(
        "apply_graph_changes",
        ToolCallSchema(
            arguments={
                "project_id": test_user_project.id,
                "expected_graph_revision": test_user_project.graph_revision,
                "expected_graph_etag": compute_graph_etag(*before),
                "patch": kafka_patch(),
            }
        ),
        async_db_session,
        who,
        None,
        None,
    )
    generated = result.result["node_ids_by_ref"]
    assert set(generated) == {"connection", "read", "commit"}
    assert set(result.result["nodes_created"]) == set(generated.values())
    nodes, edges, _ = await graph_crud.get_graph_by(
        async_db_session,
        project_id=test_user_project.id,
    )
    assert len(nodes) == 3 and len(edges) == 3
    connection_node = next(node for node in nodes if node.ui_id == generated["connection"])
    assert connection_node.input_values["connection_id"].model_dump(by_alias=True) == {
        "__dvt_type": "const",
        "value": "kafka",
    }
    assert result.result["graph_revision"] == initial_revision + 1
