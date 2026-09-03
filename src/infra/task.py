from collections.abc import Mapping
from uuid import uuid4

from src.crud import graph as graph_crud
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.dto import (
    project as project_dto,
)
from src.managers.extension_dependency_manager import get_dependency_manager
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskSource
from src.modules.task_execution.facade import build_task_lifecycle_commands
from src.modules.task_execution.infra.mappers import task_internal_to_execution
from src.modules.user.infra.fastapi.dependencies import UserAnyAuth
from src.pipeline.execution_mode import PipelineExecutionMode
from src.pipeline.graph import build_pipeline_from_graph, resolve_execution_target_nodes
from src.runtime.async_runtime import shared_orchestrator
from src.schemas.http.project_variable import ProjectVariableBase
from src.schemas.internal import ProjectVariables, TaskInternal
from src.utils.access_control import get_access_scope
from src.utils.project_variables import normalize_project_variables_storage_map


def _normalize_target_nodes(target_nodes: list[str] | None = None) -> list[str] | None:
    normalized: list[str] = []
    for node_id in target_nodes or []:
        if node_id and node_id not in normalized:
            normalized.append(node_id)
    return normalized or None


def _merge_project_variables(
        project: ProjectRecord,
        variables: Mapping[str, ProjectVariableBase] | None = None,
) -> ProjectVariables:
    project_variables = project_dto.persistent_to_project_variables(project)
    if variables is None:
        return project_variables

    base_variables = project_variables.model_dump(mode="json").get("variables") or {}
    override_variables = normalize_project_variables_storage_map(
        {
            key: value.model_dump(mode="json")
            for key, value in variables.items()
        },
        allow_legacy=False,
    ) or {}
    base_variables.update(override_variables)
    return ProjectVariables(variables=base_variables)


async def build_pending_task_from_project(
        project: ProjectRecord,
        user: UserAnyAuth,
        session: AsyncSessionDepends,
        task_id: str | None = None,
        target_nodes: list[str] | None = None,
        changed_node_ids: list[str] | None = None,
        metadata_changed_node_ids: list[str] | None = None,
        mode: PipelineExecutionMode = PipelineExecutionMode.FULL,
        send_ws_messages: bool = True,
        force_exec: bool = False,
        variables: Mapping[str, ProjectVariableBase] | None = None,
        source: TaskSource = TaskSource.API,
        schedule_run_id: str | None = None,
        schedule_attempt: int | None = None,
):
    access_scope = get_access_scope(user)
    target_nodes = _normalize_target_nodes(target_nodes)

    graph_nodes, graph_edges, _ = await graph_crud.get_graph_by(
        session,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        project_id=project.id,
        target_nodes=target_nodes,
    )

    pipeline = build_pipeline_from_graph(
        nodes=graph_nodes,
        edges=graph_edges,
        target_nodes=target_nodes,
    )
    execution_target_nodes = resolve_execution_target_nodes(
        pipeline=pipeline,
        target_nodes=target_nodes,
    )

    dirty_node_ids = changed_node_ids if changed_node_ids is not None else project.dirty_node_ids
    normalized_changed_node_ids = sorted({
        node_id
        for node_id in [*(dirty_node_ids or []), *(metadata_changed_node_ids or [])]
        if node_id in pipeline
    })

    # Собираем имена расширений из пайплайна
    from src.utils.extensions import collect_extension_names
    extension_names = collect_extension_names(pipeline)

    # Проверяем доступность расширений
    if extension_names:
        dependency_manager = get_dependency_manager()
        missing, not_ready = await dependency_manager.check_extensions_availability(extension_names)

        if missing or not_ready:
            error_message = dependency_manager.build_availability_error_message(missing, not_ready)
            raise ValueError(error_message)

    project_settings = project_dto.persistent_to_project_settings(project)
    project_variables = _merge_project_variables(project, variables=variables)

    task = TaskInternal(
        user_id=user.id,
        organization_id=project.organization_id,
        project_id=project.id,
        task_id=str(uuid4()) if task_id is None else task_id,
        pipeline=pipeline,
        extension_names=sorted(extension_names),
        mode=mode,
        force_exec=force_exec,
        send_ws_messages=send_ws_messages,
        source=source,
        metadata_changed_node_ids=metadata_changed_node_ids,
        changed_node_ids=normalized_changed_node_ids or None,
        graph_revision=(project.graph_revision if normalized_changed_node_ids else None),
        project_settings=project_settings,
        project_variables=project_variables,
        target_nodes=execution_target_nodes,
        retry_count=max(0, (schedule_attempt or 1) - 1),
        schedule_run_id=schedule_run_id,
        schedule_attempt=schedule_attempt,
    )

    lifecycle = build_task_lifecycle_commands()
    await lifecycle.create_pending_execution.execute(
        execution=task_internal_to_execution(task),
    )
    return task


async def enqueue_task_from_project(
        user: UserAnyAuth,
        session: AsyncSessionDepends,
        project: ProjectRecord,
        task_id: str | None = None,
        target_nodes: list[str] | None = None,
        changed_node_ids: list[str] | None = None,
        metadata_changed_node_ids: list[str] | None = None,
        mode: PipelineExecutionMode = PipelineExecutionMode.FULL,
        send_ws_messages: bool = True,
        force_exec: bool = False,
        variables: Mapping[str, ProjectVariableBase] | None = None,
        source: TaskSource = TaskSource.API,
        schedule_run_id: str | None = None,
        schedule_attempt: int | None = None,
):
    task = await build_pending_task_from_project(
        project=project,
        task_id=task_id,
        target_nodes=target_nodes,
        changed_node_ids=changed_node_ids,
        metadata_changed_node_ids=metadata_changed_node_ids,
        mode=mode,
        send_ws_messages=send_ws_messages,
        force_exec=force_exec,
        variables=variables,
        source=source,
        schedule_run_id=schedule_run_id,
        schedule_attempt=schedule_attempt,
        user=user,
        session=session,
    )

    orchestrator = await shared_orchestrator.get()
    try:
        await orchestrator.enqueue_task(task=task)
    except Exception:
        lifecycle = build_task_lifecycle_commands()
        await lifecycle.fail_pending_execution.execute(
            task_id=task.task_id,
            message="Failed task queue",
        )
        raise

    return task
