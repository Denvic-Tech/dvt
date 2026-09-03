from ...domain.entities import TaskExecution
from ...domain.repositories import TaskExecutionRepository
from ...domain.types import TaskTerminationReason
from ..exceptions import InvalidPendingExecutionFailureReason


class FailPendingExecutionUseCase:
    """Fail an execution before it is admitted to the worker transport."""

    def __init__(self, repository: TaskExecutionRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        task_id: str,
        termination_reason: TaskTerminationReason | None = None,
        message: str | None = None,
    ) -> TaskExecution | None:
        if termination_reason not in (None, TaskTerminationReason.NESTED_WAIT_CAPACITY_LOST):
            raise InvalidPendingExecutionFailureReason(
                f"Unsupported pending execution failure reason: {termination_reason}"
            )
        return await self._repository.fail_pending(
            task_id=task_id,
            termination_reason=termination_reason,
            message=message,
        )
