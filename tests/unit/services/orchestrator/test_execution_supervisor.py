from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.orchestrator.execution_registry import TaskExecutionRecord, TaskExecutionRegistry
from services.orchestrator.execution_supervisor import TaskExecutionSupervisor

from src import enums
from src.modules.app_settings.public.dvt_app_settings import OOMGuardConfig
from src.modules.task_execution.domain.entities import NestedWaitReservation
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskTerminationReason
from src.pipeline.execution_mode import PipelineExecutionMode

import config


class _FakeAsyncSession:
    async def commit(self):
        return None


class _FakeWorker:
    def __init__(self, *, alive: bool = True, worker_id: str = "worker-1") -> None:
        self.alive = alive
        self.worker_id = worker_id
        self.status = enums.WorkerStatus.ONLINE if alive else enums.WorkerStatus.OFFLINE
        self.is_busy = True
        self.active_task_id = "task"
        self.available_slots = 0

    def is_alive(self, *_args) -> bool:
        return self.alive


class _FakeWorkerRegistry:
    def __init__(self, worker: _FakeWorker | None = None) -> None:
        self.worker = worker

    def get(self, _worker_id: str):
        return self.worker

    def reap_dead_workers(self, _now_ts: float):
        if self.worker is not None and not self.worker.alive:
            self.worker.status = enums.WorkerStatus.OFFLINE
            self.worker.is_busy = False
            self.worker.active_task_id = None
            self.worker.available_slots = 0
            return [self.worker]
        return []

    def mark_busy(self, *, worker_id: str, task_id: str) -> None:
        del worker_id
        if self.worker is not None:
            self.worker.is_busy = True
            self.worker.active_task_id = task_id
            self.worker.available_slots = 0

    def get_alive_workers(self, _now_ts: float):
        return [self.worker] if self.worker is not None and self.worker.alive else []

    def mark_idle(self, *, worker_id: str, task_id: str | None = None) -> None:
        del worker_id, task_id
        if self.worker is None:
            return
        self.worker.is_busy = False
        self.worker.active_task_id = None
        self.worker.available_slots = 1 if self.worker.alive else 0


class _FakeScheduler:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.terminate_calls: list[str] = []
        self.registry = _FakeWorkerRegistry()

    async def request_task_hard_stop(self, *, task_id: str, reason: str) -> bool:
        self.calls.append({"task_id": task_id, "reason": reason})
        return True

    def terminate_execution(self, *, task_id: str) -> None:
        self.terminate_calls.append(task_id)


def _patch_reconciliation_tasks(monkeypatch, tasks) -> AsyncMock:
    list_reconciliation = AsyncMock(return_value=tasks)
    facade = SimpleNamespace(
        list_for_reconciliation=SimpleNamespace(execute=list_reconciliation),
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.build_task_execution_facade",
        lambda **_kwargs: facade,
    )
    return list_reconciliation


def _patch_oom_guard_settings(monkeypatch, **config) -> None:
    get_app_settings_mock = AsyncMock(
        return_value=SimpleNamespace(
            runtime=SimpleNamespace(oom_guard=OOMGuardConfig(**config)),
        )
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.get_app_settings",
        get_app_settings_mock,
    )


@pytest.mark.asyncio
async def test_reconcile_cancel_requested_marks_canceled_for_user_hard_stop(monkeypatch):
    registry = TaskExecutionRegistry()
    scheduler = _FakeScheduler()
    supervisor = TaskExecutionSupervisor(
        registry=registry,
        scheduler=scheduler,
    )
    task = SimpleNamespace(
        task_id="task-1",
        user_id="user-1",
        project_id="project-1",
        mode=PipelineExecutionMode.FULL,
        assigned_worker_id="worker-1",
        termination_reason=TaskTerminationReason.USER_HARD_STOP.value,
        updated_at=datetime.now(tz=UTC) - timedelta(seconds=30),
    )

    _patch_reconciliation_tasks(monkeypatch, [task])
    finalize_mock = AsyncMock(return_value=True)
    monkeypatch.setattr("services.orchestrator.execution_supervisor.finalize_task_terminal_status", finalize_mock)

    await supervisor._reconcile_cancel_requested_tasks()

    finalize_mock.assert_awaited_once()
    _, kwargs = finalize_mock.await_args
    assert kwargs["task_id"] == "task-1"
    assert kwargs["user_id"] == "user-1"
    assert kwargs["project_id"] == "project-1"
    assert kwargs["worker_id"] == "worker-1"
    assert kwargs["mode"] == PipelineExecutionMode.FULL
    assert kwargs["status"] == TaskExecutionStatus.CANCELLED
    assert kwargs["termination_reason"] == TaskTerminationReason.USER_HARD_STOP.value


@pytest.mark.asyncio
async def test_reconcile_cancel_requested_marks_error_for_oom_guard(monkeypatch):
    registry = TaskExecutionRegistry()
    scheduler = _FakeScheduler()
    supervisor = TaskExecutionSupervisor(
        registry=registry,
        scheduler=scheduler,
    )
    task = SimpleNamespace(
        task_id="task-2",
        user_id="user-2",
        project_id="project-2",
        mode=PipelineExecutionMode.FULL,
        assigned_worker_id="worker-2",
        termination_reason=TaskTerminationReason.OOM_GUARD.value,
        updated_at=datetime.now(tz=UTC) - timedelta(seconds=30),
    )

    _patch_reconciliation_tasks(monkeypatch, [task])
    finalize_mock = AsyncMock(return_value=True)
    monkeypatch.setattr("services.orchestrator.execution_supervisor.finalize_task_terminal_status", finalize_mock)

    await supervisor._reconcile_cancel_requested_tasks()

    finalize_mock.assert_awaited_once()
    _, kwargs = finalize_mock.await_args
    assert kwargs["task_id"] == "task-2"
    assert kwargs["user_id"] == "user-2"
    assert kwargs["project_id"] == "project-2"
    assert kwargs["worker_id"] == "worker-2"
    assert kwargs["mode"] == PipelineExecutionMode.FULL
    assert kwargs["status"] == TaskExecutionStatus.ERROR
    assert kwargs["termination_reason"] == TaskTerminationReason.OOM_GUARD.value
    assert kwargs["error_message"] == "Task terminated by OOM guard"


@pytest.mark.asyncio
async def test_user_stop_escalates_then_finishes_cancelled_without_worker_lost(monkeypatch):
    registry = TaskExecutionRegistry()
    scheduler = _FakeScheduler()
    supervisor = TaskExecutionSupervisor(registry=registry, scheduler=scheduler)
    task = SimpleNamespace(
        task_id="task-stop",
        user_id="user-1",
        project_id="project-1",
        mode=PipelineExecutionMode.FULL,
        assigned_worker_id="worker-1",
        termination_reason=TaskTerminationReason.USER_STOP.value,
        updated_at=datetime.now(tz=UTC) - timedelta(seconds=30),
    )

    _patch_reconciliation_tasks(monkeypatch, [task])
    finalize_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.finalize_task_terminal_status",
        finalize_mock,
    )

    await supervisor._reconcile_cancel_requested_tasks()

    assert scheduler.terminate_calls == ["task-stop"]
    _, kwargs = finalize_mock.await_args
    assert kwargs["status"] == TaskExecutionStatus.CANCELLED
    assert kwargs["termination_reason"] == TaskTerminationReason.USER_STOP.value


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("termination_reason", "expected_status"),
    [
        (TaskTerminationReason.USER_STOP.value, TaskExecutionStatus.CANCELLED),
        (TaskTerminationReason.USER_HARD_STOP.value, TaskExecutionStatus.CANCELLED),
        (TaskTerminationReason.OOM_GUARD.value, TaskExecutionStatus.ERROR),
    ],
)
async def test_stale_record_does_not_block_cancellation_owner(
    monkeypatch,
    termination_reason,
    expected_status,
):
    registry = TaskExecutionRegistry()
    scheduler = _FakeScheduler()
    supervisor = TaskExecutionSupervisor(registry=registry, scheduler=scheduler)
    await registry.upsert(
        TaskExecutionRecord(
            task_id="task-cancel-owner",
            worker_id="worker-1",
            hostname="host",
            pid=10,
            rss_bytes=1,
            memory_limit_bytes=None,
            system_ram_used_percent=1.0,
            timestamp=0.0,
        )
    )
    task = SimpleNamespace(
        task_id="task-cancel-owner",
        user_id="user-1",
        project_id="project-1",
        mode=PipelineExecutionMode.FULL,
        assigned_worker_id="worker-1",
        termination_reason=termination_reason,
        updated_at=datetime.now(tz=UTC) - timedelta(seconds=30),
    )

    _patch_reconciliation_tasks(monkeypatch, [task])
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.config.ORCHESTRATOR.ORCHESTRATOR_EXECUTION_TELEMETRY_STALE_TIMEOUT_SEC",
        1.0,
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.config.ORCHESTRATOR.TASK_STOP_GRACE_PERIOD_SEC",
        1.0,
    )
    finalize_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.finalize_task_terminal_status",
        finalize_mock,
    )

    await supervisor._reconcile_cancel_requested_tasks()

    finalize_mock.assert_awaited_once()
    _, kwargs = finalize_mock.await_args
    assert kwargs["status"] == expected_status
    assert kwargs["termination_reason"] == termination_reason
    assert scheduler.terminate_calls == (
        ["task-cancel-owner"]
        if termination_reason == TaskTerminationReason.USER_STOP.value
        else []
    )


@pytest.mark.asyncio
async def test_stale_telemetry_alone_does_not_infer_child_loss_without_worker_lost_signal(monkeypatch):
    registry = TaskExecutionRegistry()
    worker = _FakeWorker(alive=True, worker_id="worker-live")
    scheduler = _FakeScheduler()
    scheduler.registry = _FakeWorkerRegistry(worker)
    supervisor = TaskExecutionSupervisor(registry=registry, scheduler=scheduler)
    record = TaskExecutionRecord(
        task_id="task-live",
        worker_id="worker-live",
        hostname="host",
        pid=10,
        rss_bytes=1,
        memory_limit_bytes=None,
        system_ram_used_percent=1.0,
        timestamp=0.0,
    )
    await registry.upsert(record)
    task = SimpleNamespace(
        task_id="task-live",
        user_id="user-1",
        project_id="project-1",
        mode=PipelineExecutionMode.FULL.value,
        status=TaskExecutionStatus.RUNNING.value,
        assigned_worker_id="worker-live",
        termination_reason=None,
    )
    finalize = AsyncMock(return_value=task)
    release_nested_wait = AsyncMock()
    facade = SimpleNamespace(
        list_worker_owned_active=SimpleNamespace(execute=AsyncMock(return_value=(task,))),
        finalize_reconciled=SimpleNamespace(execute=finalize),
        release_nested_wait=SimpleNamespace(execute=release_nested_wait),
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.build_task_execution_facade",
        lambda **_kwargs: facade,
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.config.ORCHESTRATOR.ORCHESTRATOR_EXECUTION_TELEMETRY_STALE_TIMEOUT_SEC",
        1.0,
    )

    await supervisor._reconcile_stale_executions()

    assert await registry.get("task-live") is record
    assert worker.is_busy is True
    finalize.assert_not_awaited()
    release_nested_wait.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_dies_after_claim_before_first_telemetry(monkeypatch):
    registry = TaskExecutionRegistry()
    worker = _FakeWorker(alive=False, worker_id="worker-dead")
    scheduler = _FakeScheduler()
    scheduler.registry = _FakeWorkerRegistry(worker)
    supervisor = TaskExecutionSupervisor(registry=registry, scheduler=scheduler)
    task = SimpleNamespace(
        task_id="task-claimed",
        user_id="user-1",
        project_id="project-1",
        mode=PipelineExecutionMode.FULL.value,
        status=TaskExecutionStatus.STARTED.value,
        assigned_worker_id="worker-dead",
        termination_reason=None,
    )
    finalize = AsyncMock(return_value=task)
    release_nested_wait = AsyncMock()
    facade = SimpleNamespace(
        list_worker_owned_active=SimpleNamespace(execute=AsyncMock(return_value=(task,))),
        finalize_reconciled=SimpleNamespace(execute=finalize),
        release_nested_wait=SimpleNamespace(execute=release_nested_wait),
    )
    publish = AsyncMock()
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.build_task_execution_facade",
        lambda **_kwargs: facade,
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.publish_task_terminal_event",
        publish,
    )

    await supervisor._reconcile_stale_executions()

    assert await registry.get("task-claimed") is None
    finalize.assert_awaited_once_with(
        task_id="task-claimed",
        termination_reason=TaskTerminationReason.WORKER_LOST.value,
        message="Task worker heartbeat was lost",
    )
    publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_orchestrator_restart_empty_registry_recovers_running_dead_worker(monkeypatch):
    registry = TaskExecutionRegistry()
    scheduler = _FakeScheduler()
    scheduler.registry = _FakeWorkerRegistry(None)
    supervisor = TaskExecutionSupervisor(registry=registry, scheduler=scheduler)
    supervisor._started_at -= (
        config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC + 1.0
    )
    task = SimpleNamespace(
        task_id="task-restart",
        user_id="user-1",
        project_id="project-1",
        mode=PipelineExecutionMode.FULL.value,
        status=TaskExecutionStatus.RUNNING.value,
        assigned_worker_id="worker-missing",
        termination_reason=None,
    )
    finalize = AsyncMock(return_value=task)
    facade = SimpleNamespace(
        list_worker_owned_active=SimpleNamespace(execute=AsyncMock(return_value=(task,))),
        finalize_reconciled=SimpleNamespace(execute=finalize),
        release_nested_wait=SimpleNamespace(execute=AsyncMock()),
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.build_task_execution_facade",
        lambda **_kwargs: facade,
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.publish_task_terminal_event",
        AsyncMock(),
    )

    await supervisor._reconcile_stale_executions()

    finalize.assert_awaited_once()
    assert finalize.await_args.kwargs["termination_reason"] == TaskTerminationReason.WORKER_LOST.value


@pytest.mark.asyncio
async def test_terminal_task_is_not_reconciled_again_and_stale_telemetry_is_cleaned(monkeypatch):
    registry = TaskExecutionRegistry()
    worker = _FakeWorker(alive=True, worker_id="worker-terminal")
    scheduler = _FakeScheduler()
    scheduler.registry = _FakeWorkerRegistry(worker)
    supervisor = TaskExecutionSupervisor(registry=registry, scheduler=scheduler)
    await registry.upsert(
        TaskExecutionRecord(
            task_id="task-terminal",
            worker_id="worker-terminal",
            hostname="host",
            pid=10,
            rss_bytes=1,
            memory_limit_bytes=None,
            system_ram_used_percent=1.0,
            timestamp=0.0,
        )
    )
    finalize = AsyncMock(return_value=True)
    release_nested_wait = AsyncMock()
    facade = SimpleNamespace(
        list_worker_owned_active=SimpleNamespace(execute=AsyncMock(return_value=())),
        finalize_task=SimpleNamespace(execute=finalize),
        release_nested_wait=SimpleNamespace(execute=release_nested_wait),
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.build_task_execution_facade",
        lambda **_kwargs: facade,
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.config.ORCHESTRATOR.ORCHESTRATOR_EXECUTION_TELEMETRY_STALE_TIMEOUT_SEC",
        1.0,
    )

    await supervisor._reconcile_stale_executions()

    assert await registry.get("task-terminal") is None
    finalize.assert_not_awaited()
    release_nested_wait.assert_awaited_once_with(
        parent_task_id="task-terminal",
        child_task_id="task-terminal",
        worker_id="worker-terminal",
    )


@pytest.mark.asyncio
async def test_nested_wait_capacity_reduction_hard_stops_newest_evicted_parent(monkeypatch):
    registry = TaskExecutionRegistry()
    scheduler = _FakeScheduler()
    workers = [
        _FakeWorker(alive=True, worker_id="worker-a"),
        _FakeWorker(alive=True, worker_id="worker-b"),
    ]

    class _Registry(_FakeWorkerRegistry):
        def __init__(self):
            super().__init__(workers[0])

        def get_alive_workers(self, _now_ts):
            return workers

    scheduler.registry = _Registry()
    supervisor = TaskExecutionSupervisor(registry=registry, scheduler=scheduler)
    evicted = NestedWaitReservation(
        parent_task_id="parent-newest",
        child_task_id="child-newest",
        origin_worker_id="worker-b",
        created_at=datetime.now(tz=UTC),
    )
    gateway = SimpleNamespace(
        list=AsyncMock(return_value=()),
        rebalance=AsyncMock(return_value=(evicted,)),
    )
    facade = SimpleNamespace(
        nested_wait_gateway=gateway,
        release_nested_wait=SimpleNamespace(execute=AsyncMock()),
    )
    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.build_task_execution_facade",
        lambda **_kwargs: facade,
    )

    await supervisor._reconcile_nested_wait_reservations()

    gateway.rebalance.assert_awaited_once_with(max_waiters=1)
    assert scheduler.calls == [
        {
            "task_id": "parent-newest",
            "reason": TaskTerminationReason.NESTED_WAIT_CAPACITY_LOST.value,
        }
    ]


@pytest.mark.asyncio
async def test_apply_oom_guard_selects_task_with_max_rss_in_host_pressure_mode(monkeypatch):
    registry = TaskExecutionRegistry()
    scheduler = _FakeScheduler()
    supervisor = TaskExecutionSupervisor(
        registry=registry,
        scheduler=scheduler,
    )
    fake_session = _FakeAsyncSession()

    await registry.upsert(
        TaskExecutionRecord(
            task_id="task-small",
            worker_id="worker-1",
            hostname="host-1",
            pid=101,
            rss_bytes=128,
            memory_limit_bytes=1024,
            system_ram_used_percent=91.0,
            timestamp=1.0,
        )
    )
    await registry.upsert(
        TaskExecutionRecord(
            task_id="task-big",
            worker_id="worker-2",
            hostname="host-1",
            pid=202,
            rss_bytes=512,
            memory_limit_bytes=1024,
            system_ram_used_percent=91.0,
            timestamp=1.0,
        )
    )

    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.config.ORCHESTRATOR.ORCHESTRATOR_OOM_GUARD_COOLDOWN_SEC",
        0.0,
    )
    _patch_oom_guard_settings(
        monkeypatch,
        mode=enums.OOMGuardMode.HOST_PRESSURE,
        host_threshold_percent=90.0,
    )

    kill_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(supervisor, "_request_task_kill", kill_mock)

    await supervisor._apply_oom_guard(session=fake_session)

    kill_mock.assert_awaited_once_with(
        task_id="task-big",
        reason=TaskTerminationReason.OOM_GUARD.value,
    )


@pytest.mark.asyncio
async def test_apply_oom_guard_selects_worker_exceeding_percent_threshold(monkeypatch):
    registry = TaskExecutionRegistry()
    scheduler = _FakeScheduler()
    supervisor = TaskExecutionSupervisor(
        registry=registry,
        scheduler=scheduler,
    )
    fake_session = _FakeAsyncSession()

    await registry.upsert(
        TaskExecutionRecord(
            task_id="task-low",
            worker_id="worker-1",
            hostname="host-1",
            pid=101,
            rss_bytes=512,
            memory_limit_bytes=1024,
            system_ram_used_percent=50.0,
            timestamp=1.0,
        )
    )
    await registry.upsert(
        TaskExecutionRecord(
            task_id="task-high",
            worker_id="worker-2",
            hostname="host-2",
            pid=202,
            rss_bytes=900,
            memory_limit_bytes=1024,
            system_ram_used_percent=50.0,
            timestamp=1.0,
        )
    )

    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.config.ORCHESTRATOR.ORCHESTRATOR_OOM_GUARD_COOLDOWN_SEC",
        0.0,
    )
    _patch_oom_guard_settings(
        monkeypatch,
        mode=enums.OOMGuardMode.WORKER_THRESHOLD,
        worker_threshold_type=enums.OOMWorkerThresholdType.PERCENT,
        worker_threshold_percent=80.0,
    )

    kill_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(supervisor, "_request_task_kill", kill_mock)

    await supervisor._apply_oom_guard(session=fake_session)

    kill_mock.assert_awaited_once_with(
        task_id="task-high",
        reason=TaskTerminationReason.OOM_GUARD.value,
    )


@pytest.mark.asyncio
async def test_apply_oom_guard_selects_worker_exceeding_absolute_threshold(monkeypatch):
    registry = TaskExecutionRegistry()
    scheduler = _FakeScheduler()
    supervisor = TaskExecutionSupervisor(
        registry=registry,
        scheduler=scheduler,
    )
    fake_session = _FakeAsyncSession()

    await registry.upsert(
        TaskExecutionRecord(
            task_id="task-low",
            worker_id="worker-1",
            hostname="host-1",
            pid=101,
            rss_bytes=128 * 1024 * 1024,
            memory_limit_bytes=1024 * 1024 * 1024,
            system_ram_used_percent=50.0,
            timestamp=1.0,
        )
    )
    await registry.upsert(
        TaskExecutionRecord(
            task_id="task-high",
            worker_id="worker-2",
            hostname="host-2",
            pid=202,
            rss_bytes=512 * 1024 * 1024,
            memory_limit_bytes=1024 * 1024 * 1024,
            system_ram_used_percent=50.0,
            timestamp=1.0,
        )
    )

    monkeypatch.setattr(
        "services.orchestrator.execution_supervisor.config.ORCHESTRATOR.ORCHESTRATOR_OOM_GUARD_COOLDOWN_SEC",
        0.0,
    )
    _patch_oom_guard_settings(
        monkeypatch,
        mode=enums.OOMGuardMode.WORKER_THRESHOLD,
        worker_threshold_type=enums.OOMWorkerThresholdType.ABSOLUTE_MB,
        worker_threshold_mb=256,
    )

    kill_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(supervisor, "_request_task_kill", kill_mock)

    await supervisor._apply_oom_guard(session=fake_session)

    kill_mock.assert_awaited_once_with(
        task_id="task-high",
        reason=TaskTerminationReason.OOM_GUARD.value,
    )


@pytest.mark.asyncio
async def test_run_iteration_continues_when_one_step_fails(monkeypatch):
    registry = TaskExecutionRegistry()
    scheduler = _FakeScheduler()
    supervisor = TaskExecutionSupervisor(
        registry=registry,
        scheduler=scheduler,
    )

    async def fake_get_stale(*_args, **_kwargs):
        raise RuntimeError("stale lookup failed")

    reconcile_mock = AsyncMock()
    apply_oom_mock = AsyncMock()

    monkeypatch.setattr(registry, "get_stale", fake_get_stale)
    monkeypatch.setattr(supervisor, "_reconcile_cancel_requested_tasks", reconcile_mock)
    monkeypatch.setattr(supervisor, "_apply_oom_guard", apply_oom_mock)

    success = await supervisor._run_iteration(iteration=1)

    assert success is False
    reconcile_mock.assert_awaited_once()
    apply_oom_mock.assert_awaited_once()
