from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.orchestrator import task_finalizer
from services.orchestrator.execution_registry import TaskExecutionRecord, TaskExecutionRegistry

from src.modules.task_execution.domain.entities import TaskExecution
from src.modules.task_execution.domain.types import (
    TaskExecutionStatus,
    TaskSource,
    TaskTerminationReason,
)
from src.pipeline.execution_mode import PipelineExecutionMode


def _terminal_execution(*, task_id: str, status: TaskExecutionStatus, reason: str) -> TaskExecution:
    return TaskExecution(
        task_id=task_id,
        user_id="user",
        organization_id="org",
        project_id="project",
        mode=PipelineExecutionMode.FULL,
        source=TaskSource.API,
        status=status.value,
        assigned_worker_id="worker-1",
        termination_reason=reason,
    )


def _facade(*, finalized, release=None):
    return SimpleNamespace(
        finalize_reconciled=SimpleNamespace(execute=finalized),
        release_nested_wait=SimpleNamespace(execute=release or AsyncMock()),
    )


@pytest.mark.asyncio
async def test_finalize_task_terminal_status_uses_reconciliation_flow_and_sends_ws(monkeypatch):
    registry = TaskExecutionRegistry()
    await registry.upsert(
        TaskExecutionRecord(
            task_id="task-1",
            worker_id="worker-1",
            hostname="host-1",
            pid=123,
            rss_bytes=1024,
            memory_limit_bytes=4096,
            system_ram_used_percent=70.0,
            timestamp=1.0,
        )
    )
    reason = TaskTerminationReason.USER_HARD_STOP.value
    finalize = AsyncMock(
        return_value=_terminal_execution(
            task_id="task-1", status=TaskExecutionStatus.CANCELLED, reason=reason
        )
    )
    release = AsyncMock()
    fake_ws = AsyncMock()
    worker_registry = SimpleNamespace(mark_idle=lambda **_kwargs: None)

    monkeypatch.setattr(
        task_finalizer,
        "build_task_execution_facade",
        lambda **_kwargs: _facade(finalized=finalize, release=release),
    )
    monkeypatch.setattr(task_finalizer, "get_task_execution_registry", lambda: registry)
    monkeypatch.setattr(task_finalizer, "get_worker_registry", lambda: worker_registry)
    monkeypatch.setattr(task_finalizer.shared_ws_forward, "get", AsyncMock(return_value=fake_ws))

    result = await task_finalizer.finalize_task_terminal_status(
        task_id="task-1",
        user_id="user-1",
        project_id="project-1",
        worker_id="worker-1",
        mode=PipelineExecutionMode.FULL,
        status=TaskExecutionStatus.CANCELLED,
        termination_reason=reason,
    )

    assert result is True
    finalize.assert_awaited_once_with(
        task_id="task-1",
        termination_reason=reason,
        message=None,
    )
    assert await registry.get("task-1") is None
    release.assert_awaited_once_with(
        parent_task_id="task-1",
        child_task_id="task-1",
        worker_id="worker-1",
    )
    fake_ws.send_message.assert_awaited_once()
    event = fake_ws.send_message.await_args.args[0]
    assert event.status == TaskExecutionStatus.CANCELLED
    assert event.error is None


@pytest.mark.asyncio
async def test_finalize_task_terminal_status_preserves_error_payload(monkeypatch):
    registry = TaskExecutionRegistry()
    reason = TaskTerminationReason.OOM_GUARD.value
    finalize = AsyncMock(
        return_value=_terminal_execution(
            task_id="task-2", status=TaskExecutionStatus.ERROR, reason=reason
        )
    )
    fake_ws = AsyncMock()

    monkeypatch.setattr(
        task_finalizer,
        "build_task_execution_facade",
        lambda **_kwargs: _facade(finalized=finalize),
    )
    monkeypatch.setattr(task_finalizer, "get_task_execution_registry", lambda: registry)
    monkeypatch.setattr(
        task_finalizer,
        "get_worker_registry",
        lambda: SimpleNamespace(mark_idle=lambda **_kwargs: None),
    )
    monkeypatch.setattr(task_finalizer.shared_ws_forward, "get", AsyncMock(return_value=fake_ws))

    result = await task_finalizer.finalize_task_terminal_status(
        task_id="task-2",
        user_id="user-2",
        project_id="project-2",
        worker_id="worker-2",
        mode=PipelineExecutionMode.FULL,
        status=TaskExecutionStatus.ERROR,
        termination_reason=reason,
        error_message="Task terminated by OOM guard",
    )

    assert result is True
    finalize.assert_awaited_once_with(
        task_id="task-2",
        termination_reason=reason,
        message="Task terminated by OOM guard",
    )
    event = fake_ws.send_message.await_args.args[0]
    assert event.status == TaskExecutionStatus.ERROR
    assert event.error is not None
    assert event.error.message == "Task terminated by OOM guard"


@pytest.mark.asyncio
async def test_finalize_task_terminal_status_skips_cleanup_and_ws_on_cas_mismatch(monkeypatch):
    registry = TaskExecutionRegistry()
    await registry.upsert(
        TaskExecutionRecord(
            task_id="task-4",
            worker_id="worker-4",
            hostname="host-4",
            pid=789,
            rss_bytes=512,
            memory_limit_bytes=4096,
            system_ram_used_percent=65.0,
            timestamp=1.0,
        )
    )
    finalize = AsyncMock(return_value=None)
    release = AsyncMock()
    fake_ws = AsyncMock()

    monkeypatch.setattr(
        task_finalizer,
        "build_task_execution_facade",
        lambda **_kwargs: _facade(finalized=finalize, release=release),
    )
    monkeypatch.setattr(task_finalizer, "get_task_execution_registry", lambda: registry)
    monkeypatch.setattr(task_finalizer.shared_ws_forward, "get", AsyncMock(return_value=fake_ws))

    result = await task_finalizer.finalize_task_terminal_status(
        task_id="task-4",
        user_id="user-4",
        project_id="project-4",
        worker_id="worker-4",
        mode=PipelineExecutionMode.FULL,
        status=TaskExecutionStatus.CANCELLED,
        termination_reason=TaskTerminationReason.USER_HARD_STOP.value,
    )

    assert result is False
    assert await registry.get("task-4") is not None
    release.assert_not_awaited()
    fake_ws.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_commit_redis_cleanup_failure_does_not_block_terminal_ws(monkeypatch):
    registry = TaskExecutionRegistry()
    reason = TaskTerminationReason.OOM_GUARD.value
    finalize = AsyncMock(
        return_value=_terminal_execution(
            task_id="task-redis-failure", status=TaskExecutionStatus.ERROR, reason=reason
        )
    )
    release = AsyncMock(side_effect=RuntimeError("valkey unavailable"))
    fake_ws = AsyncMock()

    monkeypatch.setattr(
        task_finalizer,
        "build_task_execution_facade",
        lambda **_kwargs: _facade(finalized=finalize, release=release),
    )
    monkeypatch.setattr(task_finalizer, "get_task_execution_registry", lambda: registry)
    monkeypatch.setattr(
        task_finalizer,
        "get_worker_registry",
        lambda: SimpleNamespace(mark_idle=lambda **_kwargs: None),
    )
    monkeypatch.setattr(task_finalizer.shared_ws_forward, "get", AsyncMock(return_value=fake_ws))

    result = await task_finalizer.finalize_task_terminal_status(
        task_id="task-redis-failure",
        user_id="user-1",
        project_id="project-1",
        worker_id="worker-1",
        mode=PipelineExecutionMode.FULL,
        status=TaskExecutionStatus.ERROR,
        termination_reason=reason,
        error_message="failed",
    )

    assert result is True
    release.assert_awaited_once()
    fake_ws.send_message.assert_awaited_once()
