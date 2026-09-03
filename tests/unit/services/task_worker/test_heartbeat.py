import pytest

from services.task_worker import heartbeat as heartbeat_module
from services.task_worker.execution_slot import mark_execution_slot_busy, mark_execution_slot_idle
from services.task_worker.schemas import HeartbeatPayload


async def _capture_single_heartbeat(monkeypatch):
    sender = heartbeat_module.HeartbeatSender()
    payloads: list[HeartbeatPayload] = []

    async def _publish(_channel, payload, **_kwargs):
        payloads.append(HeartbeatPayload.model_validate_json(payload))
        sender._shutdown_event.set()

    monkeypatch.setattr(sender, "_publish_with_retries", _publish)
    monkeypatch.setattr(heartbeat_module, "get_sys_info", lambda: None)
    monkeypatch.setattr(heartbeat_module, "get_worker_id", lambda: "worker-test")
    await sender._run_loop()
    assert len(payloads) == 1
    return payloads[0]


@pytest.mark.asyncio
async def test_idle_heartbeat_reports_one_available_execution_slot(monkeypatch):
    mark_execution_slot_idle()

    payload = await _capture_single_heartbeat(monkeypatch)

    assert payload.active_task_id is None
    assert payload.is_busy is False
    assert payload.available_slots == 1


@pytest.mark.asyncio
async def test_busy_heartbeat_reports_active_task_and_no_available_slots(monkeypatch):
    mark_execution_slot_busy("task-running")
    try:
        payload = await _capture_single_heartbeat(monkeypatch)
    finally:
        mark_execution_slot_idle(task_id="task-running")

    assert payload.active_task_id == "task-running"
    assert payload.is_busy is True
    assert payload.available_slots == 0
