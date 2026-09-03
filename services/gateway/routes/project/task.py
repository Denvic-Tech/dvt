from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query
from usrak.core.dependencies.user import build_user_dependency
from usrak.core.enums import AuthMode

from services.gateway.deps import (
    clients as client_deps,
)
from services.gateway.deps.project import UserProjectByPath
from services.gateway.routes.impl import task as task_impl

from src.clients.orchestrator_client import GrpcOrchestratorClient
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.task_execution.domain.types import TaskSource
from src.modules.task_execution.infra.http_schemas import TaskCreateRequest, TaskInfo, TaskResponse
from src.modules.user.infra.db_models import UserRecord
from src.pipeline.execution_mode import PipelineExecutionMode

router = APIRouter(prefix="/tasks", tags=["Tasks"])

_get_user = build_user_dependency(
    auth_mode=AuthMode.ACCESS_ONLY,
    require_verified=True,
    require_active=True,
)

UserDepends = Annotated[UserRecord, Depends(_get_user)]


@router.post("/new", response_model=TaskResponse)
async def create_task(
    session: AsyncSessionDepends,
    user: UserDepends,
    project: UserProjectByPath,
    payload: TaskCreateRequest | None = Body(default=None),
    mode: Annotated[PipelineExecutionMode, Query(description="Режим выполнения задачи")] = PipelineExecutionMode.FULL,
    force_exec: Annotated[bool, Query(description="Принудительное выполнение")] = False,
    target_nodes: Annotated[
        list[str] | None, Query(description="Список целевых узлов для выполнения")
    ] = None,
):
    return await task_impl.create_task_route_impl(
        session=session,
        user=user,
        project=project,
        target_nodes=target_nodes,
        mode=mode,
        force_exec=force_exec,
        variables=None if payload is None else payload.variables,
        source=TaskSource.UI,
    )


@router.post(
    "/{task_id}/cancel",
    response_model=TaskResponse,
)
async def cancel_task(
    project_id: str,
    task_id: str,
    session: AsyncSessionDepends,
    user: UserDepends,
    orchestrator: Annotated[GrpcOrchestratorClient, Depends(client_deps.get_orchestrator_client)],
):
    """
    Запрашивает отмену задачи. Возвращает 404 если задача не найдена.
    """
    return await task_impl.cancel_task_route_impl(
        project_id=project_id,
        task_id=task_id,
        session=session,
        user=user,
        orchestrator=orchestrator,
    )


@router.get(
    "/{task_id}/info",
    response_model=TaskInfo,
    summary="Получить текущее состояние задачи",
)
async def get_task_info(
    project_id: str, task_id: str, user: UserDepends, session: AsyncSessionDepends
):
    """
    Возвращает текущее состояние задачи, или 404 если не найдено.
    """
    return await task_impl.get_task_info_route_impl(
        project_id=project_id,
        task_id=task_id,
        session=session,
        user=user,
    )
