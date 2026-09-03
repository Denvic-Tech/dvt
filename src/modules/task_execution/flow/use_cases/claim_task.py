from ...domain.repositories import TaskExecutionRepository


class ClaimTaskUseCase:
    def __init__(self, repository: TaskExecutionRepository) -> None:
        self._repository = repository

    async def execute(self, *, task_id: str, worker_id: str) -> bool:
        return await self._repository.claim(task_id=task_id, worker_id=worker_id)
