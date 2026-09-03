from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field
from datetime import UTC, datetime

from src.pipeline.execution_mode import PipelineExecutionMode

from .types import TaskExecutionStatus, TaskSource, TaskTerminationReason


@dataclass(frozen=True, slots=True)
class TaskExecution:
    """Authoritative lifecycle state of one pipeline execution."""

    task_id: str
    user_id: str
    organization_id: str
    project_id: str
    mode: PipelineExecutionMode
    source: TaskSource
    status: TaskExecutionStatus
    force_exec: bool = False
    queued_at: datetime = dataclass_field(default_factory=lambda: datetime.now(tz=UTC))
    schedule_run_id: str | None = None
    schedule_attempt: int | None = None
    assigned_worker_id: str | None = None
    # Unknown historical values are kept as strings until old rows disappear.
    termination_reason: TaskTerminationReason | str | None = None
    message: str | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DispatchOutboxItem:
    """A durable request to deliver a task payload to an execution transport."""

    dispatch_id: str
    task_id: str
    payload: Mapping[str, object]
    created_at: datetime
    published_at: datetime | None = None
    attempts: int = 0


@dataclass(frozen=True, slots=True)
class EnqueueTaskResult:
    """Result of durable enqueue including root executions superseded atomically."""

    execution: TaskExecution
    superseded: tuple[TaskExecution, ...] = ()


@dataclass(frozen=True, slots=True)
class NestedWaitReservation:
    """One worker slot occupied by a parent waiting synchronously for a child task."""

    parent_task_id: str
    child_task_id: str
    origin_worker_id: str
    created_at: datetime = dataclass_field(default_factory=lambda: datetime.now(tz=UTC))


@dataclass(frozen=True, slots=True)
class NestedWaitDecision:
    accepted: bool
    error: str | None = None
