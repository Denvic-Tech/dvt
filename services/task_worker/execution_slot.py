from __future__ import annotations

import multiprocessing
from dataclasses import dataclass

_MAX_TASK_ID_BYTES = 512
_active_task_id = multiprocessing.Array("c", _MAX_TASK_ID_BYTES, lock=True)


@dataclass(frozen=True, slots=True)
class ExecutionSlotSnapshot:
    active_task_id: str | None
    is_busy: bool
    available_slots: int


def mark_execution_slot_busy(task_id: str) -> None:
    encoded = task_id.encode("utf-8")
    if len(encoded) >= _MAX_TASK_ID_BYTES:
        raise ValueError(f"Task id is too long for worker execution slot state: {len(encoded)} bytes")
    with _active_task_id.get_lock():
        _active_task_id.value = encoded


def mark_execution_slot_idle(*, task_id: str | None = None) -> None:
    with _active_task_id.get_lock():
        current = _active_task_id.value.decode("utf-8") or None
        if task_id is not None and current not in (None, task_id):
            return
        _active_task_id.value = b""


def get_execution_slot_snapshot() -> ExecutionSlotSnapshot:
    with _active_task_id.get_lock():
        active_task_id = _active_task_id.value.decode("utf-8") or None
    return ExecutionSlotSnapshot(
        active_task_id=active_task_id,
        is_busy=active_task_id is not None,
        available_slots=0 if active_task_id is not None else 1,
    )
