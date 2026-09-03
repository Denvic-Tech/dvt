from enum import StrEnum


class TaskExecutionStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"  # Legacy rows only; never produced for new executions.
    STARTED = "STARTED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"


class TaskSource(StrEnum):
    UI = "UI"
    API = "API"
    SCHEDULER = "SCHEDULER"
    NODE = "NODE"
    MCP = "MCP"


class TaskTerminationReason(StrEnum):
    USER_STOP = "USER_STOP"
    USER_HARD_STOP = "USER_HARD_STOP"
    OOM_GUARD = "OOM_GUARD"
    WORKER_LOST = "WORKER_LOST"
    NESTED_WAIT_CAPACITY_LOST = "NESTED_WAIT_CAPACITY_LOST"
    SUPERSEDED_BY_NEWER_EXECUTION = "SUPERSEDED_BY_NEWER_EXECUTION"


class TaskControlCommand(StrEnum):
    STOP = "STOP"
    HARD_STOP = "HARD_STOP"


ROOT_EXECUTION_SOURCES = frozenset(
    {TaskSource.UI, TaskSource.API, TaskSource.SCHEDULER, TaskSource.MCP}
)
TERMINAL_STATUSES = frozenset({
    TaskExecutionStatus.SUCCESS,
    TaskExecutionStatus.ERROR,
    TaskExecutionStatus.CANCELLED,
})
SUPERSEDABLE_STATUSES = frozenset({TaskExecutionStatus.PENDING, TaskExecutionStatus.QUEUED})
CLAIMABLE_STATUSES = frozenset({TaskExecutionStatus.QUEUED, TaskExecutionStatus.ASSIGNED})
WORKER_OWNED_ACTIVE_STATUSES = frozenset({TaskExecutionStatus.STARTED, TaskExecutionStatus.RUNNING})
CANCELLABLE_ACTIVE_STATUSES = frozenset({
    TaskExecutionStatus.ASSIGNED,
    TaskExecutionStatus.STARTED,
    TaskExecutionStatus.RUNNING,
    TaskExecutionStatus.CANCEL_REQUESTED,
})
RECONCILIATION_TERMINATION_REASONS = frozenset({
    TaskTerminationReason.USER_STOP,
    TaskTerminationReason.USER_HARD_STOP,
    TaskTerminationReason.OOM_GUARD,
    TaskTerminationReason.WORKER_LOST,
    TaskTerminationReason.NESTED_WAIT_CAPACITY_LOST,
})
