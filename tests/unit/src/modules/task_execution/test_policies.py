import pytest

from src.modules.task_execution.domain.policies import (
    choose_termination_reason,
    terminal_status_for_termination_reason,
)
from src.modules.task_execution.domain.types import TaskTerminationReason


@pytest.mark.parametrize(
    ("current", "requested", "hard", "expected"),
    [
        (None, TaskTerminationReason.USER_STOP.value, False, TaskTerminationReason.USER_STOP.value),
        (None, TaskTerminationReason.USER_STOP.value, True, TaskTerminationReason.USER_HARD_STOP.value),
        (TaskTerminationReason.USER_STOP.value, TaskTerminationReason.USER_HARD_STOP.value, True, TaskTerminationReason.USER_HARD_STOP.value),
        (TaskTerminationReason.USER_HARD_STOP.value, TaskTerminationReason.USER_STOP.value, False, TaskTerminationReason.USER_HARD_STOP.value),
        (TaskTerminationReason.USER_STOP.value, TaskTerminationReason.WORKER_LOST.value, False, TaskTerminationReason.USER_STOP.value),
        (TaskTerminationReason.USER_HARD_STOP.value, TaskTerminationReason.WORKER_LOST.value, False, TaskTerminationReason.USER_HARD_STOP.value),
        (TaskTerminationReason.USER_STOP.value, TaskTerminationReason.OOM_GUARD.value, True, TaskTerminationReason.OOM_GUARD.value),
        (TaskTerminationReason.WORKER_LOST.value, TaskTerminationReason.OOM_GUARD.value, True, TaskTerminationReason.OOM_GUARD.value),
        (TaskTerminationReason.OOM_GUARD.value, TaskTerminationReason.WORKER_LOST.value, False, TaskTerminationReason.OOM_GUARD.value),
    ],
)
def test_termination_reason_precedence_is_order_independent_for_known_reasons(
    current,
    requested,
    hard,
    expected,
):
    assert choose_termination_reason(
        current=current,
        requested=requested,
        hard=hard,
    ) == expected


@pytest.mark.parametrize(
    ("reason", "status"),
    [
        (TaskTerminationReason.USER_STOP.value, "CANCELLED"),
        (TaskTerminationReason.USER_HARD_STOP.value, "CANCELLED"),
        (TaskTerminationReason.OOM_GUARD.value, "ERROR"),
        (TaskTerminationReason.WORKER_LOST.value, "ERROR"),
        (TaskTerminationReason.NESTED_WAIT_CAPACITY_LOST.value, "ERROR"),
    ],
)
def test_termination_reason_defines_terminal_semantics(reason, status):
    assert terminal_status_for_termination_reason(reason) == status
