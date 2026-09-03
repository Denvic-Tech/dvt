from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.gateway.routes import queue as queue_module

from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.schemas.http.queue import QueueAction, QueueActionRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("task_status", [TaskExecutionStatus.QUEUED, TaskExecutionStatus.RUNNING])
async def test_queue_cancel_routes_queued_and_running_tasks_through_orchestrator(
    monkeypatch,
    task_status,
):
    task = SimpleNamespace(
        task_id="task-1",
        user_id="user-1",
        status=task_status,
    )
    get_task = AsyncMock(return_value=task)
    orchestrator = SimpleNamespace(cancel_task=AsyncMock())
    session = SimpleNamespace(commit=AsyncMock())
    user = SimpleNamespace(id="user-1")

    monkeypatch.setattr(queue_module, "get_accessible_task_by_id", get_task)
    monkeypatch.setattr(
        queue_module,
        "get_access_scope",
        lambda _user: SimpleNamespace(organization_id="org-1", owner_user_id="user-1"),
    )

    response = await queue_module.post_queue(
        payload=QueueActionRequest(action=QueueAction.CANCEL, task_id="task-1"),
        session=session,
        user=user,
        orchestrator=orchestrator,
    )

    assert response.success is True
    orchestrator.cancel_task.assert_awaited_once_with(task_id="task-1")
    session.commit.assert_not_awaited()
