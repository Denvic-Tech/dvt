from __future__ import annotations

import pytest

from services.orchestrator.execution_registry import TaskExecutionRecord, TaskExecutionRegistry
from services.orchestrator.deps import worker_event_callbacks
from src.schemas.event import (
    TaskExecutionStatusEvent,
    TaskExecutionTelemetryEvent,
)
from src.schemas.worker_event_payload import WorkerEventPayload


@pytest.mark.asyncio
async def test_handle_worker_event_upserts_task_execution_telemetry(monkeypatch):
    registry = TaskExecutionRegistry()
    monkeypatch.setattr(worker_event_callbacks, "get_task_execution_registry", lambda: registry)

    payload = WorkerEventPayload(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        worker_id="worker-1",
        event=TaskExecutionTelemetryEvent(
            task_id="task-1",
            hostname="host-1",
            pid=321,
            rss_bytes=4096,
            memory_limit_bytes=8192,
            system_ram_used_percent=82.5,
        ),
    )

    await worker_event_callbacks.handle_worker_event(payload)

    record = await registry.get("task-1")
    assert record is not None
    assert record.hostname == "host-1"
    assert record.pid == 321
    assert record.rss_bytes == 4096
    assert record.memory_limit_bytes == 8192


@pytest.mark.asyncio
async def test_telemetry_recovery_updates_retained_stale_record_and_keeps_worker_busy(monkeypatch):
    registry = TaskExecutionRegistry()
    stale_record = TaskExecutionRecord(
        task_id="task-recovery",
        worker_id="worker-1",
        hostname="old-host",
        pid=111,
        rss_bytes=1024,
        memory_limit_bytes=8192,
        system_ram_used_percent=50.0,
        timestamp=1.0,
    )
    await registry.upsert(stale_record)

    busy_calls: list[tuple[str, str]] = []
    fake_worker_registry = type(
        "FakeWorkerRegistry",
        (),
        {
            "mark_busy": lambda self, *, worker_id, task_id: busy_calls.append(
                (worker_id, task_id)
            )
        },
    )()
    monkeypatch.setattr(worker_event_callbacks, "get_task_execution_registry", lambda: registry)
    monkeypatch.setattr(worker_event_callbacks, "get_worker_registry", lambda: fake_worker_registry)
    monkeypatch.setattr(worker_event_callbacks.time, "time", lambda: 123.0)

    payload = WorkerEventPayload(
        user_id="user-1",
        project_id="project-1",
        task_id="task-recovery",
        worker_id="worker-1",
        event=TaskExecutionTelemetryEvent(
            task_id="task-recovery",
            hostname="new-host",
            pid=222,
            rss_bytes=4096,
            memory_limit_bytes=8192,
            system_ram_used_percent=60.0,
        ),
    )

    await worker_event_callbacks.handle_worker_event(payload)

    recovered = await registry.get("task-recovery")
    assert recovered is not None
    assert recovered.timestamp == 123.0
    assert recovered.hostname == "new-host"
    assert recovered.pid == 222
    assert recovered.rss_bytes == 4096
    assert busy_calls == [("worker-1", "task-recovery")]
