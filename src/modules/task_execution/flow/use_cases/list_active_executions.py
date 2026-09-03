from ...domain.entities import TaskExecution
from ...domain.repositories import TaskExecutionRepository


class ListWorkerOwnedActiveExecutionsUseCase:
    """Read authoritative worker-owned active executions for recovery/reconciliation."""

    def __init__(self, repository: TaskExecutionRepository) -> None:
        self._repository = repository

    async def execute(self, *, limit: int = 1000) -> tuple[TaskExecution, ...]:
        return tuple(await self._repository.list_worker_owned_active(limit=limit))
