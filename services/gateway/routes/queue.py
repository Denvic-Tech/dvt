"""
Роутер для управления очередью выполнения задач.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from services.gateway.deps.clients import get_orchestrator_client

from src.clients.orchestrator_client import GrpcOrchestratorClient
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.exceptions import FailedProcessTaskException, UnsupportedActionException
from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.modules.task_execution.infra.queries import (
    get_accessible_task_by_id,
    list_queue_tasks,
)
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.queue import (
    QueueAction,
    QueueActionRequest,
    QueueActionResponse,
    QueueStateResponse,
    QueueTask,
)
from src.utils.access_control import get_access_scope

router = APIRouter(prefix="/queue", tags=["Queue Management"])


StatusFilterQuery = Annotated[
    list[TaskExecutionStatus] | None,
    Query(
        description=(
            "Список статусов для фильтрации. "
            "По умолчанию используется только PENDING.\n"
            "Пример: ?status_filter=PENDING&status_filter=RUNNING"
        ),
    ),
]


@router.get(
    "",
    summary="Получить список задач в очереди",
    response_model=QueueStateResponse,
)
async def get_queue(
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    project_id: Annotated[str | None, Query()] = None,
    status_filter: StatusFilterQuery = None,
) -> QueueStateResponse:
    """
    Возвращает список задач из очереди, ожидающих выполнения.
    """

    if not status_filter:
        status_filter = [TaskExecutionStatus.PENDING]
    access_scope = get_access_scope(user)

    task_entries = await list_queue_tasks(
        session,
        statuses=status_filter,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        project_id=project_id,
    )
    queue_tasks = [QueueTask.model_validate(entry) for entry in task_entries]
    return QueueStateResponse(tasks=queue_tasks)


@router.post(
    "",
    status_code=status.HTTP_200_OK,
    summary="Выполнить действие над очередью",
    response_model=QueueActionResponse,
)
async def post_queue(
    payload: QueueActionRequest,
    session: AsyncSessionDepends,
    user: UserAccessOnly,
    orchestrator: Annotated[GrpcOrchestratorClient, Depends(get_orchestrator_client)],
) -> QueueActionResponse:
    """
    Позволяет отменить ожидающие задачи.
    """
    if payload.action == QueueAction.CANCEL:
        access_scope = get_access_scope(user)
        task_entry = await get_accessible_task_by_id(
            session,
            organization_id=access_scope.organization_id,
            owner_user_id=access_scope.owner_user_id,
            task_id=payload.task_id,
        )
        if not task_entry:
            raise FailedProcessTaskException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Failed cancel task"
            )

        await orchestrator.cancel_task(task_id=payload.task_id)
        return QueueActionResponse(
            success=True,
            message="Task cancelled.",
            task_id=payload.task_id,
        )

    raise UnsupportedActionException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported queue action: {payload.action}",
    )
