from ...domain.entities import TaskExecution
from ...domain.repositories import TaskExecutionRepository
from ...domain.types import (
    RECONCILIATION_TERMINATION_REASONS,
    TaskExecutionStatus,
    TaskTerminationReason,
)
from ..exceptions import InvalidReconciliationTerminationReason


class GetTaskExecutionUseCase:
    def __init__(self, repository: TaskExecutionRepository) -> None:
        self._repository = repository

    async def execute(self, *, task_id: str) -> TaskExecution | None:
        return await self._repository.get(task_id=task_id)


class ListExecutionsForReconciliationUseCase:
    def __init__(self, repository: TaskExecutionRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        statuses: tuple[TaskExecutionStatus, ...] | list[TaskExecutionStatus],
        limit: int = 1000,
    ) -> tuple[TaskExecution, ...]:
        return tuple(
            await self._repository.list_for_reconciliation(statuses=statuses, limit=limit)
        )


class FinalizeReconciledExecutionUseCase:
    """System-owned finalization for explicit reconciliation scenarios only."""

    def __init__(self, repository: TaskExecutionRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        task_id: str,
        termination_reason: TaskTerminationReason,
        message: str | None = None,
    ) -> TaskExecution | None:
        if termination_reason not in RECONCILIATION_TERMINATION_REASONS:
            raise InvalidReconciliationTerminationReason(
                f"Termination reason is not valid for reconciliation: {termination_reason}"
            )
        return await self._repository.finalize_reconciled(
            task_id=task_id,
            termination_reason=termination_reason,
            message=message,
        )
