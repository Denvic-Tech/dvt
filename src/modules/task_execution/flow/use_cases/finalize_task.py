from ...domain.repositories import TaskExecutionRepository
from ...domain.types import TaskExecutionStatus, TaskTerminationReason


class FinalizeTaskUseCase:
    def __init__(self, repository: TaskExecutionRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        task_id: str,
        worker_id: str,
        status: TaskExecutionStatus,
        message: str | None = None,
        termination_reason: TaskTerminationReason | str | None = None,
    ) -> bool:
        return await self._repository.finalize(
            task_id=task_id,
            worker_id=worker_id,
            status=status,
            message=message,
            termination_reason=termination_reason,
        )
