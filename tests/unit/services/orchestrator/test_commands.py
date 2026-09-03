from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.orchestrator.deps import commands as commands_module

from src import enums
from src.modules.task_execution.domain.entities import (
    EnqueueTaskResult,
    NestedWaitDecision,
    TaskExecution,
)
from src.modules.task_execution.domain.types import (
    TaskExecutionStatus,
    TaskSource,
    TaskTerminationReason,
)
from src.modules.task_execution.flow.use_cases import FailPendingExecutionUseCase
from src.pipeline.execution_mode import PipelineExecutionMode


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class _FakeAsyncSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


class _FakeAsyncSessionLocal:
    async def __aenter__(self):
        return _FakeAsyncSession()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeWorkerRegistry:
    def __init__(self, alive_workers):
        self._alive_workers = alive_workers

    def get_alive_workers(self, _now_ts):
        return self._alive_workers


@pytest.mark.asyncio
async def test_accept_task_enqueue_persists_durable_dispatch_without_memory_scheduler(monkeypatch):
    execution = TaskExecution(
        task_id="child-task-1", user_id="user-1", organization_id="org-1",
        project_id="project-1", mode="full", source="API", status="QUEUED",
    )
    enqueue = AsyncMock(return_value=EnqueueTaskResult(execution=execution))
    facade = SimpleNamespace(enqueue_task_internal=enqueue)
    monkeypatch.setattr(commands_module, "build_task_execution_facade", lambda **_kwargs: facade)

    task = SimpleNamespace(task_id="child-task-1", user_id="user-1", project_id="project-1")
    decision = await commands_module.accept_task_enqueue(task)

    assert decision.accepted is True
    assert decision.should_schedule is True
    enqueue.assert_awaited_once_with(task)


@pytest.mark.asyncio
async def test_handle_nested_task_enqueue_rejects_pending_child_through_real_flow(monkeypatch):
    accept_mock = AsyncMock()
    publish_mock = AsyncMock()
    pending = TaskExecution(
        task_id="child-task-1",
        user_id="user-1",
        organization_id="org-1",
        project_id="project-2",
        mode=PipelineExecutionMode.FULL,
        source=TaskSource.NODE,
        status=TaskExecutionStatus.PENDING,
    )

    class _PendingRepository:
        async def fail_pending(self, *, task_id, termination_reason, message=None):
            nonlocal pending
            assert task_id == pending.task_id
            assert pending.status == TaskExecutionStatus.PENDING.value
            pending = TaskExecution(
                task_id=pending.task_id,
                user_id=pending.user_id,
                organization_id=pending.organization_id,
                project_id=pending.project_id,
                mode=pending.mode,
                source=pending.source,
                status=TaskExecutionStatus.ERROR,
                termination_reason=termination_reason,
                message=message,
            )
            return pending

    registry = _FakeWorkerRegistry(
        [SimpleNamespace(worker_id="worker-1", status=enums.WorkerStatus.ONLINE)]
    )
    reserve = AsyncMock(return_value=NestedWaitDecision(
        accepted=False,
        error="Nested wait is not allowed: no alive workers are available besides origin worker worker-1.",
    ))
    facade = SimpleNamespace(
        reserve_nested_wait=SimpleNamespace(execute=reserve),
        fail_pending_execution=FailPendingExecutionUseCase(_PendingRepository()),
    )
    monkeypatch.setattr(commands_module, "build_task_execution_facade", lambda **_kwargs: facade)
    monkeypatch.setattr(commands_module, "get_worker_registry", lambda: registry)
    monkeypatch.setattr(commands_module, "publish_task_terminal_event", publish_mock)
    monkeypatch.setattr(commands_module, "accept_task_enqueue", accept_mock)

    command = SimpleNamespace(
        request_id="child-task-1",
        origin_worker_id="worker-1",
        parent_task_id="parent-task-1",
        wait_for_completion=True,
        task=SimpleNamespace(
            task_id="child-task-1",
            user_id="user-1",
            project_id="project-2",
            mode=PipelineExecutionMode.FULL,
        ),
    )

    await commands_module.handle_nested_task_enqueue(command)

    assert pending.status == TaskExecutionStatus.ERROR.value
    assert pending.termination_reason == TaskTerminationReason.NESTED_WAIT_CAPACITY_LOST.value
    assert "no alive workers are available besides origin worker" in (pending.message or "")
    publish_mock.assert_awaited_once()
    accept_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_nested_task_enqueue_allows_fire_and_forget_without_other_alive_workers(monkeypatch):
    accept_mock = AsyncMock(
        return_value=commands_module.TaskEnqueueDecision(
            accepted=True,
            task_id="child-task-1",
            should_schedule=True,
        )
    )
    registry = _FakeWorkerRegistry(
        [SimpleNamespace(worker_id="worker-1", status=enums.WorkerStatus.ONLINE)]
    )

    monkeypatch.setattr(commands_module, "get_worker_registry", lambda: registry)
    monkeypatch.setattr(commands_module, "accept_task_enqueue", accept_mock)

    command = SimpleNamespace(
        request_id="child-task-1",
        origin_worker_id="worker-1",
        parent_task_id="parent-task-1",
        wait_for_completion=False,
        task=SimpleNamespace(
            task_id="child-task-1",
            user_id="user-1",
            project_id="project-2",
            mode=PipelineExecutionMode.FULL,
        ),
    )

    await commands_module.handle_nested_task_enqueue(command)

    accept_mock.assert_awaited_once()
