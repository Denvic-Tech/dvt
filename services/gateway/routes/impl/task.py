from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.orchestrator_client import GrpcOrchestratorClient
from src.exceptions import TaskNotFoundException
from src.infra.task import enqueue_task_from_project
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskSource
from src.modules.task_execution.infra.http_mapping import task_read_to_info
from src.modules.task_execution.infra.http_schemas import TaskResponse
from src.modules.task_execution.infra.queries import get_accessible_task
from src.modules.user.infra.db_models import UserRecord
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.project_variable import ProjectVariableBase
from src.utils.access_control import get_access_scope


async def create_task_route_impl(
        session: AsyncSession,
        project: ProjectRecord,
        user: UserRecord,
        target_nodes: list[str] | None,
        mode: PipelineExecutionMode,
        force_exec: bool,
        source: TaskSource,
        variables: dict[str, ProjectVariableBase] | None = None,
):
    task = await enqueue_task_from_project(
        project=project,
        target_nodes=target_nodes,
        mode=mode,
        force_exec=force_exec,
        variables=variables,
        user=user,
        session=session,
        source=source,
    )

    return TaskResponse(
        success=True,
        message="Task queued.",
        task_id=task.task_id
    )


async def cancel_task_route_impl(
        project_id: str,
        task_id: str,
        session: AsyncSession,
        user: UserRecord,
        orchestrator: GrpcOrchestratorClient,
):
    access_scope = get_access_scope(user)
    task = await get_accessible_task(
        session=session,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        project_id=project_id,
        task_id=task_id,
    )

    if not task:
        raise TaskNotFoundException(status_code=404, detail=f"Task ID={task_id} not found.")

    await orchestrator.cancel_task(
        task_id=task.task_id,
    )

    return TaskResponse(
        success=True,
        message="Task cancellation requested.",
        task_id=task.task_id,
    )


async def get_task_info_route_impl(
        project_id: str,
        task_id: str,
        session: AsyncSession,
        user: UserRecord,
):
    access_scope = get_access_scope(user)
    task = await get_accessible_task(
        session=session,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        project_id=project_id,
        task_id=task_id,
    )

    if not task:
        raise TaskNotFoundException(status_code=404, detail=f"Task ID={task_id} not found.")

    task_info = task_read_to_info(task)

    return task_info
