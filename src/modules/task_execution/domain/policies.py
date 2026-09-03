from collections.abc import Collection

from .entities import NestedWaitDecision
from .types import (
    CLAIMABLE_STATUSES,
    TaskExecutionStatus,
    ROOT_EXECUTION_SOURCES,
    SUPERSEDABLE_STATUSES,
    TaskSource,
    TaskTerminationReason,
)

_TERMINATION_REASON_PRIORITY = {
    TaskTerminationReason.SUPERSEDED_BY_NEWER_EXECUTION: 10,
    # Once an intentional user termination is authoritative in PostgreSQL, a
    # subsequent prefork process exit must not be reclassified as WORKER_LOST.
    TaskTerminationReason.WORKER_LOST: 50,
    TaskTerminationReason.USER_STOP: 100,
    TaskTerminationReason.USER_HARD_STOP: 200,
    TaskTerminationReason.NESTED_WAIT_CAPACITY_LOST: 300,
    TaskTerminationReason.OOM_GUARD: 400,
}

_FAILURE_TERMINATION_REASONS = frozenset({
    TaskTerminationReason.OOM_GUARD,
    TaskTerminationReason.WORKER_LOST,
    TaskTerminationReason.NESTED_WAIT_CAPACITY_LOST,
})


def can_supersede(*, source: TaskSource, status: TaskExecutionStatus) -> bool:
    """Only not-yet-started root executions can be coalesced."""
    return source in ROOT_EXECUTION_SOURCES and status in SUPERSEDABLE_STATUSES


def can_claim(status: TaskExecutionStatus) -> bool:
    """ASSIGNED is accepted exclusively to drain records from the old scheduler."""
    return status in CLAIMABLE_STATUSES


def normalize_termination_request(
    *,
    reason: TaskTerminationReason | str,
    hard: bool,
) -> TaskTerminationReason | str:
    """Turn transport intent into a domain reason before precedence is applied."""
    if hard and reason == TaskTerminationReason.USER_STOP:
        return TaskTerminationReason.USER_HARD_STOP
    return reason


def choose_termination_reason(
    *,
    current: TaskTerminationReason | str | None,
    requested: TaskTerminationReason | str,
    hard: bool,
) -> TaskTerminationReason | str:
    """Resolve concurrent termination requests deterministically.

    Unknown legacy reasons are preserved unless a known request arrives. System
    failures outrank user cancellation, and an explicit hard stop outranks STOP.
    """
    requested = normalize_termination_request(reason=requested, hard=hard)
    if current is None or current == requested:
        return requested

    current_priority = _TERMINATION_REASON_PRIORITY.get(current)
    requested_priority = _TERMINATION_REASON_PRIORITY.get(requested)
    if requested_priority is None:
        return current
    if current_priority is None:
        return requested
    return requested if requested_priority > current_priority else current


def terminal_status_for_termination_reason(
    reason: TaskTerminationReason | str | None,
) -> TaskExecutionStatus:
    """Map an authoritative termination reason to its terminal lifecycle status."""
    return (
        TaskExecutionStatus.ERROR
        if reason in _FAILURE_TERMINATION_REASONS
        else TaskExecutionStatus.CANCELLED
    )


def decide_nested_wait_reservation(
    *,
    origin_worker_id: str,
    alive_worker_ids: Collection[str],
    reserved_origin_worker_ids: Collection[str],
) -> NestedWaitDecision:
    """Keep at least one alive worker slot outside synchronous parent waits."""
    alive = set(alive_worker_ids)
    if origin_worker_id not in alive:
        return NestedWaitDecision(
            accepted=False,
            error=f"Nested wait origin worker {origin_worker_id} is not alive.",
        )

    other_alive = alive - {origin_worker_id}
    if not other_alive:
        return NestedWaitDecision(
            accepted=False,
            error=(
                "Nested wait is not allowed: no alive workers are available "
                f"besides origin worker {origin_worker_id}."
            ),
        )

    active_waiters = set(reserved_origin_worker_ids) & alive
    prospective_waiters = active_waiters | {origin_worker_id}
    if len(prospective_waiters) >= len(alive):
        return NestedWaitDecision(
            accepted=False,
            error=(
                "Nested wait rejected to prevent distributed deadlock: "
                f"{len(prospective_waiters)} parent waits would occupy all "
                f"{len(alive)} alive worker slots."
            ),
        )

    return NestedWaitDecision(accepted=True)
