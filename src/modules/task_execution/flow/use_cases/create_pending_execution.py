from ...domain.entities import TaskExecution
from ...domain.repositories import TaskExecutionRepository
from ...domain.types import TaskExecutionStatus


class CreatePendingExecutionUseCase:
    """Persist a prepared execution before it is admitted to dispatch."""

    def __init__(self, repository: TaskExecutionRepository) -> None:
        self._repository = repository

    async def execute(self, *, execution: TaskExecution) -> TaskExecution:
        if execution.status != TaskExecutionStatus.PENDING:
            raise ValueError("Only PENDING executions can be created before dispatch")
        return await self._repository.create_pending(execution)
