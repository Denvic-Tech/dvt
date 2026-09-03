from collections.abc import Sequence
from typing import Protocol

from ..entities import EnqueueTaskResult, TaskExecution
from ..types import TaskExecutionStatus, TaskTerminationReason


class TaskExecutionRepository(Protocol):
    """Persistence contract for lifecycle transitions and their outbox transaction."""

    async def create_pending(self, execution: TaskExecution) -> TaskExecution: ...

    async def enqueue_with_dispatch(
        self,
        execution: TaskExecution,
        payload: dict[str, object],
    ) -> EnqueueTaskResult: ...

    async def claim(self, *, task_id: str, worker_id: str) -> bool: ...

    async def mark_running(self, *, task_id: str, worker_id: str) -> bool: ...

    async def finalize(
        self,
        *,
        task_id: str,
        worker_id: str,
        status: TaskExecutionStatus,
        message: str | None = None,
        termination_reason: TaskTerminationReason | str | None = None,
    ) -> bool: ...

    async def finalize_reconciled(
        self,
        *,
        task_id: str,
        termination_reason: TaskTerminationReason,
        message: str | None = None,
    ) -> TaskExecution | None: ...

    async def fail_pending(
        self,
        *,
        task_id: str,
        termination_reason: TaskTerminationReason | None,
        message: str | None = None,
    ) -> TaskExecution | None: ...

    async def get(self, *, task_id: str) -> TaskExecution | None: ...

    async def list_for_reconciliation(
        self,
        *,
        statuses: Sequence[TaskExecutionStatus],
        limit: int = 1000,
    ) -> Sequence[TaskExecution]: ...

    async def request_stop(
        self,
        *,
        task_id: str,
        reason: TaskTerminationReason,
        hard: bool,
    ) -> TaskExecution | None: ...

    async def list_worker_owned_active(self, *, limit: int = 1000) -> Sequence[TaskExecution]: ...
