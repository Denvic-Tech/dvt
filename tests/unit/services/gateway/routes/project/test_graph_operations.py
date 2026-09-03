from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.gateway.routes.project.graph import graph_operations as graph_operations_module
from services.gateway.routes.project.graph.graph_operations import (
    GraphOperationsAggregated,
    _collect_computational_seed_node_ids,
    _collect_metadata_seed_node_ids,
    _has_processed_graph_changes,
    _has_requested_computational_changes,
    _node_patch_updates_input_values,
    process_graph_op,
)

from src.enums import DVTDefaultRoles
from src.modules.pipeline_graph.infra.schemas import (
    GraphEdgeUISchema,
    GraphNodeUISchema,
    GraphNodeUIUpdateSchema,
)
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord


class _LockedProjectResult:
    def __init__(self, project: ProjectRecord | None) -> None:
        self._project = project

    def scalar_one_or_none(self) -> ProjectRecord | None:
        return self._project


def _make_user() -> UserRecord:
    return UserRecord(
        id="user-1",
        email="user-1@example.com",
        hashed_password="hashed",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.USER.value,
        organization_id="org-1",
    )


def _make_project() -> ProjectRecord:
    return ProjectRecord(
        id="project-1",
        name="Project",
        user_id="user-1",
        organization_id="org-1",
    )


def _make_node_payload() -> GraphNodeUISchema:
    return GraphNodeUISchema.model_validate(
        {
            "id": "node-1",
            "type": "test-node",
            "position": {"x": 1.0, "y": 2.0},
            "selected": False,
            "data": {
                "name": "node",
                "displayName": "Node",
                "inputValues": {},
            },
        }
    )


def test_node_patch_updates_input_values_detects_input_value_patch():
    patch = GraphNodeUIUpdateSchema.model_validate(
        {
            "id": "node-1",
            "data": {
                "inputValues": {
                    "value_in": {"__dvt_type": "const", "value": "hello"},
                }
            },
        }
    )

    assert _node_patch_updates_input_values(patch) is True


def test_collect_metadata_seed_node_ids_uses_input_patches_and_edge_targets():
    payload = GraphOperationsAggregated(
        nodes_to_update=[
            GraphNodeUIUpdateSchema.model_validate(
                {
                    "id": "node-1",
                    "data": {
                        "inputValues": {
                            "value_in": {"__dvt_type": "const", "value": "hello"},
                        }
                    },
                }
            ),
            GraphNodeUIUpdateSchema.model_validate(
                {
                    "id": "node-2",
                    "subgraphId": "subgraph-1",
                }
            ),
        ],
        edges_to_create=[
            GraphEdgeUISchema(
                id="edge-1",
                type="default",
                source="source-1",
                sourceHandle="output-value_out",
                target="target-1",
                targetHandle="input-value_in",
            )
        ],
    )

    assert _collect_metadata_seed_node_ids(payload) == ["node-1", "target-1"]


def test_collect_computational_seed_node_ids_uses_old_and_new_edge_targets():
    payload = GraphOperationsAggregated.model_validate(
        {
            "edges_to_delete": [{"id": "edge-delete"}],
            "edges_to_update": [{"id": "edge-update", "target": "new-target"}],
        }
    )
    existing_edges = [
        SimpleNamespace(ui_id="edge-delete", source="source-1", target="deleted-edge-target"),
        SimpleNamespace(ui_id="edge-update", source="source-2", target="old-target"),
    ]

    assert _collect_computational_seed_node_ids(
        payload,
        existing_edges=existing_edges,
    ) == ["deleted-edge-target", "new-target", "old-target"]


def test_visual_only_node_patch_is_not_computational_change():
    payload = GraphOperationsAggregated(
        nodes_to_update=[
            GraphNodeUIUpdateSchema.model_validate(
                {"id": "node-1", "position": {"x": 10.0, "y": 20.0}}
            )
        ]
    )

    assert _has_requested_computational_changes(payload) is False


def test_subgraph_only_edge_patch_is_not_computational_change():
    payload = GraphOperationsAggregated.model_validate(
        {"edges_to_update": [{"id": "edge-1", "subgraphId": "subgraph-1"}]}
    )

    assert _has_requested_computational_changes(payload) is False
    assert (
        _collect_computational_seed_node_ids(
            payload,
            existing_edges=[SimpleNamespace(ui_id="edge-1", source="source", target="target")],
        )
        == []
    )


def test_has_processed_graph_changes_detects_empty_result() -> None:
    assert (
        _has_processed_graph_changes(
            nodes_deleted=[],
            nodes_created=[],
            nodes_updated=[],
            edges_deleted=[],
            edges_created=[],
            edges_updated=[],
            subgraphs_deleted=[],
            subgraphs_created=[],
            subgraphs_updated=[],
        )
        is False
    )


def test_has_processed_graph_changes_detects_reference_cleanup() -> None:
    assert (
        _has_processed_graph_changes(
            nodes_deleted=[],
            nodes_created=[],
            nodes_updated=[],
            edges_deleted=[],
            edges_created=[],
            edges_updated=[],
            subgraphs_deleted=[],
            subgraphs_created=[],
            subgraphs_updated=[],
            subgraph_reference_rows_cleared=1,
        )
        is True
    )


@pytest.mark.asyncio
async def test_process_graph_op_marks_project_dirty_after_computational_change(monkeypatch) -> None:
    project = _make_project()
    session = AsyncMock()
    session.execute.return_value = _LockedProjectResult(project)
    monkeypatch.setattr(
        graph_operations_module.graph_crud,
        "create_graph_nodes",
        AsyncMock(side_effect=lambda *, session, nodes: nodes),
    )
    monkeypatch.setattr(
        graph_operations_module.graph_crud,
        "get_graph_edges_by",
        AsyncMock(return_value=[]),
    )
    mark_dirty = AsyncMock(return_value=project)
    monkeypatch.setattr(
        graph_operations_module.project_crud, "mark_project_graph_dirty", mark_dirty
    )
    touch = AsyncMock(return_value=True)
    monkeypatch.setattr(graph_operations_module.project_crud, "touch_project_updated_at", touch)
    monkeypatch.setattr(graph_operations_module, "increment_graph_operation", lambda *args: None)

    response = await process_graph_op(
        project_id=project.id,
        payload=GraphOperationsAggregated(nodes_to_create=[_make_node_payload()]),
        user=_make_user(),
        session=session,
    )

    assert response.nodes_created == ["node-1"]
    mark_dirty.assert_awaited_once_with(
        session=session,
        project_id=project.id,
        organization_id=project.organization_id,
        node_ids=["node-1"],
        removed_node_ids=[],
    )
    touch.assert_not_awaited()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_graph_op_scopes_metadata_task_to_current_metadata_seeds(monkeypatch) -> None:
    project = _make_project()
    project.dirty_node_ids = ["broken-node"]
    user = _make_user()
    session = AsyncMock()
    session.execute.return_value = _LockedProjectResult(project)
    payload = GraphOperationsAggregated(
        nodes_to_update=[
            GraphNodeUIUpdateSchema.model_validate(
                {
                    "id": "changed-node",
                    "data": {
                        "inputValues": {
                            "value_in": {"__dvt_type": "const", "value": "hello"},
                        }
                    },
                }
            )
        ]
    )

    monkeypatch.setattr(
        graph_operations_module.graph_crud,
        "get_graph_edges_by",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        graph_operations_module.graph_crud,
        "update_graph_nodes",
        AsyncMock(return_value=[SimpleNamespace(ui_id="changed-node", type="test-node")]),
    )
    monkeypatch.setattr(
        graph_operations_module.project_crud,
        "mark_project_graph_dirty",
        AsyncMock(return_value=project),
    )
    monkeypatch.setattr(
        graph_operations_module.graph_crud,
        "get_graph_by",
        AsyncMock(return_value=([], [], [])),
    )
    monkeypatch.setattr(graph_operations_module, "increment_graph_operation", lambda *args: None)

    collected_seed_node_ids = []

    def fake_collect_affected_terminal_node_ids(*, nodes, edges, seed_node_ids):
        collected_seed_node_ids.extend(seed_node_ids)
        return ["target-node"]

    monkeypatch.setattr(
        graph_operations_module,
        "collect_affected_terminal_node_ids",
        fake_collect_affected_terminal_node_ids,
    )
    enqueue_task = AsyncMock(return_value=SimpleNamespace(task_id="metadata-task"))
    monkeypatch.setattr(graph_operations_module, "enqueue_task_from_project", enqueue_task)

    response = await process_graph_op(
        project_id=project.id,
        payload=payload,
        user=user,
        session=session,
    )

    assert response.task_id == "metadata-task"
    assert collected_seed_node_ids == ["changed-node"]
    enqueue_task.assert_awaited_once_with(
        project=project,
        target_nodes=["target-node"],
        mode=graph_operations_module.PipelineExecutionMode.METADATA_ONLY,
        force_exec=True,
        user=user,
        session=session,
        source=graph_operations_module.TaskSource.UI,
        changed_node_ids=["changed-node"],
        metadata_changed_node_ids=["changed-node"],
    )


@pytest.mark.asyncio
async def test_process_graph_op_does_not_touch_project_without_graph_change(monkeypatch) -> None:
    project = _make_project()
    project.dirty_node_ids = ["previously-dirty-node"]
    session = AsyncMock()
    session.execute.return_value = _LockedProjectResult(project)
    monkeypatch.setattr(
        graph_operations_module.graph_crud,
        "get_graph_edges_by",
        AsyncMock(return_value=[]),
    )
    touch = AsyncMock(return_value=True)
    monkeypatch.setattr(graph_operations_module.project_crud, "touch_project_updated_at", touch)

    response = await process_graph_op(
        project_id=project.id,
        payload=GraphOperationsAggregated(),
        user=_make_user(),
        session=session,
    )

    assert response == graph_operations_module.GraphOperationResponse()
    touch.assert_not_awaited()
    session.commit.assert_awaited_once()
