from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.orchestrator import scheduler as scheduler_module


class _Registry:
    def reap_dead_workers(self, _now):
        return []


class _Publisher:
    def __init__(self):
        self.calls = 0

    async def execute(self):
        self.calls += 1
        return 2


class _UseCase:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class _SyncUseCase:
    def __init__(self):
        self.calls = []

    def execute(self, **kwargs):
        self.calls.append(kwargs)


def _facade(*, stop_result=None, kill_result=None):
    return SimpleNamespace(
        publish_pending_dispatches=_Publisher(),
        request_stop=_UseCase(stop_result),
        kill_task=_UseCase(kill_result),
        terminate_execution=_SyncUseCase(),
        release_nested_wait=_UseCase(),
    )


@pytest.mark.asyncio
async def test_tick_publishes_durable_outbox_without_selecting_worker(monkeypatch):
    facade = _facade()
    monkeypatch.setattr(scheduler_module, "build_task_execution_facade", lambda **_kwargs: facade)

    scheduler = scheduler_module.TaskScheduler(registry=_Registry())
    await scheduler._tick()

    assert facade.publish_pending_dispatches.calls == 1
    assert not hasattr(scheduler, "_pending_tasks")


@pytest.mark.asyncio
async def test_hard_stop_delegates_to_task_execution_kill_use_case(monkeypatch):
    task = SimpleNamespace(status="CANCEL_REQUESTED", termination_reason="OOM_GUARD")
    facade = _facade(kill_result=task)
    monkeypatch.setattr(scheduler_module, "build_task_execution_facade", lambda **_kwargs: facade)

    scheduler = scheduler_module.TaskScheduler(registry=_Registry())

    assert await scheduler.request_task_hard_stop(task_id="task", reason="OOM_GUARD")
    assert facade.kill_task.calls == [{"task_id": "task", "reason": "OOM_GUARD"}]


@pytest.mark.asyncio
async def test_running_stop_stays_cancel_requested_and_uses_cooperative_execution_flow(monkeypatch):
    task = SimpleNamespace(
        task_id="task",
        user_id="user",
        project_id="project",
        mode="full",
        status="CANCEL_REQUESTED",
        termination_reason="USER_STOP",
    )
    facade = _facade(stop_result=task)
    publish = AsyncMock()
    monkeypatch.setattr(scheduler_module, "build_task_execution_facade", lambda **_kwargs: facade)
    monkeypatch.setattr(scheduler_module, "publish_task_terminal_event", publish)
    scheduler = scheduler_module.TaskScheduler(registry=_Registry())

    assert await scheduler.handle_task_cancel(task_id="task")

    assert facade.request_stop.calls == [{"task_id": "task", "reason": "USER_STOP"}]
    assert facade.release_nested_wait.calls == []
    publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_queued_stop_publishes_terminal_event_and_releases_nested_child(monkeypatch):
    task = SimpleNamespace(
        task_id="task",
        user_id="user",
        project_id="project",
        mode="full",
        status="CANCELLED",
        termination_reason="USER_STOP",
    )
    facade = _facade(stop_result=task)
    publish = AsyncMock()
    monkeypatch.setattr(scheduler_module, "build_task_execution_facade", lambda **_kwargs: facade)
    monkeypatch.setattr(scheduler_module, "publish_task_terminal_event", publish)
    scheduler = scheduler_module.TaskScheduler(registry=_Registry())

    assert await scheduler.request_task_stop(task_id="task", reason="USER_STOP")

    assert facade.release_nested_wait.calls == [{"child_task_id": "task"}]
    publish.assert_awaited_once()


def test_stop_escalation_delegates_to_terminate_use_case(monkeypatch):
    facade = _facade()
    monkeypatch.setattr(scheduler_module, "build_task_execution_facade", lambda **_kwargs: facade)
    scheduler = scheduler_module.TaskScheduler(registry=_Registry())

    scheduler.terminate_execution(task_id="task")

    assert facade.terminate_execution.calls == [{"task_id": "task"}]
