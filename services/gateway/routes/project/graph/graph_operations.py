import sqlalchemy as sa
from fastapi import APIRouter
from pydantic import BaseModel
from pystructor import pick

from services.gateway.metrics.runtime import increment_graph_operation

from src import enums
from src.crud import graph as graph_crud, project as project_crud
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.exceptions import ProjectNotFoundException
from src.infra.task import enqueue_task_from_project
from src.logger import logger
from src.modules.pipeline_graph.infra.db_models import GraphEdgeRecord, GraphNodeRecord
from src.modules.pipeline_graph.infra.mappers import (
    graph_edges as graph_edges_dto,
    graph_nodes as graph_nodes_dto,
    subgraphs as subgraphs_dto,
)
from src.modules.pipeline_graph.infra.schemas import (
    GraphEdgeUISchema,
    GraphEdgeUpdateUISchema,
    GraphNodeUISchema,
    GraphNodeUIUpdateSchema,
    SubgraphUISchema,
    SubgraphUIUpdateSchema,
)
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskSource
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.pipeline.execution_mode import PipelineExecutionMode
from src.pipeline.graph import collect_affected_terminal_node_ids
from src.utils.access_control import get_access_scope

router = r = APIRouter(tags=["Graph Operations"])


class GraphOperationsAggregated(BaseModel):
    nodes_to_delete: list[pick(GraphNodeUISchema, "id")(BaseModel)] = []
    nodes_to_create: list[GraphNodeUISchema] = []
    nodes_to_update: list[GraphNodeUIUpdateSchema] = []

    edges_to_delete: list[pick(GraphEdgeUISchema, "id")(BaseModel)] = []
    edges_to_create: list[GraphEdgeUISchema] = []
    edges_to_update: list[GraphEdgeUpdateUISchema] = []

    subgraphs_to_delete: list[pick(SubgraphUISchema, "id")(BaseModel)] = []
    subgraphs_to_create: list[SubgraphUISchema] = []
    subgraphs_to_update: list[SubgraphUIUpdateSchema] = []


class GraphOperationResponse(BaseModel):
    nodes_deleted: list[str] = []
    nodes_created: list[str] = []
    nodes_updated: list[str] = []

    edges_deleted: list[str] = []
    edges_created: list[str] = []
    edges_updated: list[str] = []

    subgraphs_deleted: list[str] = []
    subgraphs_created: list[str] = []
    subgraphs_updated: list[str] = []

    task_id: str | None = None


def _is_subgraph_only_node_patch(node_patch: GraphNodeUIUpdateSchema) -> bool:
    payload = node_patch.model_dump(exclude_unset=True)
    return set(payload.keys()).issubset({"id", "subgraphId"})


def _is_subgraph_only_edge_patch(edge_patch: GraphEdgeUpdateUISchema) -> bool:
    payload = edge_patch.model_dump(exclude_unset=True)
    return set(payload.keys()).issubset({"id", "subgraphId"})


def _node_patch_updates_input_values(node_patch: GraphNodeUIUpdateSchema) -> bool:
    payload = node_patch.model_dump(exclude_unset=True)
    node_data = payload.get("data") or {}
    return "inputValues" in node_data


def _collect_metadata_seed_node_ids(payload: GraphOperationsAggregated) -> list[str]:
    seed_node_ids: list[str] = []

    for node_patch in payload.nodes_to_update:
        if _node_patch_updates_input_values(node_patch) and node_patch.id not in seed_node_ids:
            seed_node_ids.append(node_patch.id)

    for edge in payload.edges_to_create:
        if edge.target not in seed_node_ids:
            seed_node_ids.append(edge.target)

    return seed_node_ids


def _collect_computational_seed_node_ids(
    payload: GraphOperationsAggregated,
    *,
    existing_edges: list[GraphEdgeRecord],
) -> list[str]:
    seed_node_ids = set(_collect_metadata_seed_node_ids(payload))
    seed_node_ids.update(node.id for node in payload.nodes_to_create)

    for node_patch in payload.nodes_to_update:
        node_payload = node_patch.model_dump(exclude_unset=True)
        data_payload = node_payload.get("data") or {}
        if set(data_payload).intersection({"name", "inputValues", "storeEnabled"}):
            seed_node_ids.add(node_patch.id)

    existing_edges_by_id = {edge.ui_id: edge for edge in existing_edges}
    deleted_node_ids = {node.id for node in payload.nodes_to_delete}
    for edge in existing_edges:
        if edge.source in deleted_node_ids:
            seed_node_ids.add(edge.target)

    for edge_payload in payload.edges_to_delete:
        existing_edge = existing_edges_by_id.get(edge_payload.id)
        if existing_edge is not None:
            seed_node_ids.add(existing_edge.target)

    for edge_patch in payload.edges_to_update:
        if _is_subgraph_only_edge_patch(edge_patch):
            continue
        existing_edge = existing_edges_by_id.get(edge_patch.id)
        if existing_edge is not None:
            seed_node_ids.add(existing_edge.target)
        patch_payload = edge_patch.model_dump(exclude_unset=True)
        target = patch_payload.get("target")
        if target:
            seed_node_ids.add(target)

    return sorted(seed_node_ids - deleted_node_ids)


def _has_requested_computational_changes(payload: GraphOperationsAggregated) -> bool:
    if any(
        (
            payload.nodes_to_create,
            payload.nodes_to_delete,
            payload.edges_to_create,
            payload.edges_to_delete,
        )
    ):
        return True

    if any(not _is_subgraph_only_edge_patch(edge_patch) for edge_patch in payload.edges_to_update):
        return True

    return any(
        set(node_patch.model_dump(exclude_unset=True).get("data") or {}).intersection(
            {"name", "inputValues", "storeEnabled"}
        )
        for node_patch in payload.nodes_to_update
    )


def _has_processed_graph_changes(
    *,
    nodes_deleted: list[str],
    nodes_created: list[str],
    nodes_updated: list[str],
    edges_deleted: list[str],
    edges_created: list[str],
    edges_updated: list[str],
    subgraphs_deleted: list[str],
    subgraphs_created: list[str],
    subgraphs_updated: list[str],
    subgraph_reference_rows_cleared: int = 0,
) -> bool:
    return any(
        (
            nodes_deleted,
            nodes_created,
            nodes_updated,
            edges_deleted,
            edges_created,
            edges_updated,
            subgraphs_deleted,
            subgraphs_created,
            subgraphs_updated,
            subgraph_reference_rows_cleared,
        )
    )


async def _process_graph_op_impl(
    project_id: str,
    payload: GraphOperationsAggregated,
    user,
    session,
    *,
    source: TaskSource,
):
    access_scope = get_access_scope(user)
    project_filters = [
        ProjectRecord.id == project_id,
        ProjectRecord.is_deleted.is_(False),
    ]
    if access_scope.organization_id is not None:
        project_filters.append(ProjectRecord.organization_id == access_scope.organization_id)
    if access_scope.owner_user_id is not None:
        project_filters.append(ProjectRecord.user_id == access_scope.owner_user_id)
    project = (
        await session.execute(sa.select(ProjectRecord).where(*project_filters).with_for_update())
    ).scalar_one_or_none()

    if not project:
        raise ProjectNotFoundException(project_id=project_id)

    owner_user_id = user.id if access_scope.is_owner_scoped else project.user_id
    organization_id = project.organization_id
    metadata_seed_node_ids = _collect_metadata_seed_node_ids(payload)
    existing_edges = list(
        await graph_crud.get_graph_edges_by(
            session=session,
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            project_id=project.id,
        )
    )
    computational_seed_node_ids = _collect_computational_seed_node_ids(
        payload,
        existing_edges=existing_edges,
    )

    nodes_deleted, nodes_created, nodes_updated = [], [], []
    edges_deleted, edges_created, edges_updated = [], [], []
    subgraphs_deleted, subgraphs_created, subgraphs_updated = [], [], []
    subgraph_reference_rows_cleared = 0

    persistent_subgraphs_to_create = [
        subgraphs_dto.to_persistent(
            subgraph,
            project_id=project.id,
            user_id=owner_user_id,
            organization_id=organization_id,
        )
        for subgraph in payload.subgraphs_to_create
    ]
    if persistent_subgraphs_to_create:
        res = await graph_crud.create_subgraphs(
            session=session,
            subgraphs=persistent_subgraphs_to_create,
        )
        subgraphs_created = [subgraph.ui_id for subgraph in res]
        increment_graph_operation("subgraph_create", len(subgraphs_created))

    persistent_nodes_to_delete = [
        graph_nodes_dto.to_persistent(
            node, project_id=project.id, user_id=owner_user_id, organization_id=organization_id
        )
        for node in payload.nodes_to_delete
    ]
    if persistent_nodes_to_delete:
        res = await graph_crud.delete_graph_nodes_by(
            session=session,
            project_id=project.id,
            ui_id=[node.ui_id for node in persistent_nodes_to_delete],
        )
        nodes_deleted = [node.ui_id for node in res]
        increment_graph_operation("node_delete", len(nodes_deleted))

    persistent_nodes_to_create = [
        graph_nodes_dto.to_persistent(
            node, project_id=project.id, user_id=owner_user_id, organization_id=organization_id
        )
        for node in payload.nodes_to_create
    ]
    if persistent_nodes_to_create:
        res = await graph_crud.create_graph_nodes(
            session=session,
            nodes=persistent_nodes_to_create,
        )
        nodes_created = [node.ui_id for node in res]
        increment_graph_operation("node_create", len(nodes_created))

    persistent_nodes_to_patch = []
    for node in payload.nodes_to_update:
        persistent_node = graph_nodes_dto.to_persistent(
            node,
            project_id=project.id,
            user_id=owner_user_id,
            organization_id=organization_id,
        )
        persistent_nodes_to_patch.append(persistent_node)

    if persistent_nodes_to_patch:
        res = await graph_crud.update_graph_nodes(
            session=session,
            nodes=persistent_nodes_to_patch,
        )
        nodes_updated = [node.ui_id for node in res]
        increment_graph_operation("node_update", len(nodes_updated))

        is_subgraph_only_patch = all(
            _is_subgraph_only_node_patch(node_patch) for node_patch in payload.nodes_to_update
        )

        if res and not is_subgraph_only_patch:
            nodes_types = [node.type for node in res]
            # Если все обновленные ноды - виджеты, то не нужно запускать пересчет графа
            if all(node_type == enums.NodeType.WIDGET.value.lower() for node_type in nodes_types):
                widget_node_ids = {node.ui_id for node in res}
                metadata_seed_node_ids = [
                    node_id for node_id in metadata_seed_node_ids if node_id not in widget_node_ids
                ]

    persistent_edges_to_delete = [
        graph_edges_dto.to_persistent(
            edge, project_id=project.id, user_id=owner_user_id, organization_id=organization_id
        )
        for edge in payload.edges_to_delete
    ]
    if persistent_edges_to_delete:
        res = await graph_crud.delete_graph_edges_by(
            session=session,
            project_id=project.id,
            ui_id=[edge.ui_id for edge in persistent_edges_to_delete],
        )
        edges_deleted = [edge.ui_id for edge in res]
        increment_graph_operation("edge_delete", len(edges_deleted))

    persistent_edges_to_create = [
        graph_edges_dto.to_persistent(
            edge, project_id=project.id, user_id=owner_user_id, organization_id=organization_id
        )
        for edge in payload.edges_to_create
    ]
    if persistent_edges_to_create:
        res = await graph_crud.create_graph_edges(
            session=session,
            edges=persistent_edges_to_create,
        )
        edges_created = [edge.ui_id for edge in res]
        increment_graph_operation("edge_create", len(edges_created))

    persistent_edges_to_patch = [
        graph_edges_dto.to_persistent(
            edge, project_id=project.id, user_id=owner_user_id, organization_id=organization_id
        )
        for edge in payload.edges_to_update
    ]
    if persistent_edges_to_patch:
        res = await graph_crud.update_graph_edges(
            session=session,
            edges=persistent_edges_to_patch,
        )
        edges_updated = [edge.ui_id for edge in res]
        increment_graph_operation("edge_update", len(edges_updated))

        is_subgraph_only_patch = all(
            _is_subgraph_only_edge_patch(edge_patch) for edge_patch in payload.edges_to_update
        )

    persistent_subgraphs_to_patch = [
        subgraphs_dto.to_persistent(
            subgraph,
            project_id=project.id,
            user_id=owner_user_id,
            organization_id=organization_id,
        )
        for subgraph in payload.subgraphs_to_update
    ]
    if persistent_subgraphs_to_patch:
        res = await graph_crud.update_subgraphs(
            session=session,
            subgraphs=persistent_subgraphs_to_patch,
        )
        subgraphs_updated = [subgraph.ui_id for subgraph in res]
        increment_graph_operation("subgraph_update", len(subgraphs_updated))

    persistent_subgraphs_to_delete = [
        subgraphs_dto.to_persistent(
            subgraph,
            project_id=project.id,
            user_id=owner_user_id,
            organization_id=organization_id,
        )
        for subgraph in payload.subgraphs_to_delete
    ]
    if persistent_subgraphs_to_delete:
        subgraph_ui_ids = [subgraph.ui_id for subgraph in persistent_subgraphs_to_delete]

        # Перед удалением subgraph нужно очистить ссылки у нод/ребер.
        clear_node_refs_result = await session.execute(
            sa.update(GraphNodeRecord)
            .where(
                GraphNodeRecord.project_id == project.id,
                GraphNodeRecord.subgraph_id.in_(subgraph_ui_ids),
            )
            .values(subgraph_id=None)
        )
        subgraph_reference_rows_cleared += clear_node_refs_result.rowcount or 0

        clear_edge_refs_result = await session.execute(
            sa.update(GraphEdgeRecord)
            .where(
                GraphEdgeRecord.project_id == project.id,
                GraphEdgeRecord.subgraph_id.in_(subgraph_ui_ids),
            )
            .values(subgraph_id=None)
        )
        subgraph_reference_rows_cleared += clear_edge_refs_result.rowcount or 0

        res = await graph_crud.delete_subgraphs_by(
            session=session,
            project_id=project.id,
            ui_id=subgraph_ui_ids,
        )
        subgraphs_deleted = [subgraph.ui_id for subgraph in res]
        increment_graph_operation("subgraph_delete", len(subgraphs_deleted))

    graph_changed = _has_processed_graph_changes(
        nodes_deleted=nodes_deleted,
        nodes_created=nodes_created,
        nodes_updated=nodes_updated,
        edges_deleted=edges_deleted,
        edges_created=edges_created,
        edges_updated=edges_updated,
        subgraphs_deleted=subgraphs_deleted,
        subgraphs_created=subgraphs_created,
        subgraphs_updated=subgraphs_updated,
        subgraph_reference_rows_cleared=subgraph_reference_rows_cleared,
    )
    computational_graph_changed = graph_changed and _has_requested_computational_changes(payload)
    if computational_graph_changed:
        dirty_project = await project_crud.mark_project_graph_dirty(
            session=session,
            project_id=project.id,
            organization_id=organization_id,
            node_ids=computational_seed_node_ids,
            removed_node_ids=nodes_deleted,
        )
        if dirty_project is not None:
            project = dirty_project
    elif graph_changed:
        await project_crud.touch_project_updated_at(
            session=session,
            project_id=project.id,
            organization_id=organization_id,
        )

    await session.commit()

    task_id = None
    affected_target_node_ids = None
    should_infer_metadata = computational_graph_changed and bool(metadata_seed_node_ids)
    if should_infer_metadata:
        graph_nodes, graph_edges, _ = await graph_crud.get_graph_by(
            session=session,
            organization_id=access_scope.organization_id,
            owner_user_id=access_scope.owner_user_id,
            project_id=project.id,
        )
        affected_target_node_ids = collect_affected_terminal_node_ids(
            nodes=graph_nodes,
            edges=graph_edges,
            seed_node_ids=metadata_seed_node_ids,
        )

    if should_infer_metadata and affected_target_node_ids:
        logger.info("Queueing metadata inference task after graph operations")
        task = await enqueue_task_from_project(
            project=project,
            target_nodes=affected_target_node_ids,
            mode=PipelineExecutionMode.METADATA_ONLY,
            force_exec=True,
            user=user,
            session=session,
            source=source,
            changed_node_ids=metadata_seed_node_ids,
            metadata_changed_node_ids=metadata_seed_node_ids,
        )
        task_id = task.task_id

    return GraphOperationResponse(
        nodes_deleted=nodes_deleted,
        nodes_created=nodes_created,
        nodes_updated=nodes_updated,
        edges_deleted=edges_deleted,
        edges_created=edges_created,
        edges_updated=edges_updated,
        subgraphs_deleted=subgraphs_deleted,
        subgraphs_created=subgraphs_created,
        subgraphs_updated=subgraphs_updated,
        task_id=task_id,
    )


class ApplyGraphOperationsUseCase:
    """Shared atomic graph-operation orchestration for UI and internal adapters."""

    async def execute(
        self,
        *,
        project_id: str,
        payload: GraphOperationsAggregated,
        user,
        session,
        source: TaskSource,
    ) -> GraphOperationResponse:
        return await _process_graph_op_impl(
            project_id=project_id,
            payload=payload,
            user=user,
            session=session,
            source=source,
        )


@r.post("", response_model=GraphOperationResponse)
async def process_graph_op(
    project_id: str,
    payload: GraphOperationsAggregated,
    user: UserAccessOnly,
    session: AsyncSessionDepends,
):
    return await ApplyGraphOperationsUseCase().execute(
        project_id=project_id,
        payload=payload,
        user=user,
        session=session,
        source=TaskSource.UI,
    )
