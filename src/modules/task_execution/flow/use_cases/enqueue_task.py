from ...domain.entities import EnqueueTaskResult, TaskExecution
from ...domain.gateways import TaskTransport
from ...domain.repositories import TaskExecutionRepository


class EnqueueTaskUseCase:
    def __init__(self, repository: TaskExecutionRepository, transport: TaskTransport) -> None:
        self._repository = repository
        self._transport = transport

    async def execute(
        self,
        *,
        execution: TaskExecution,
        payload: dict[str, object],
    ) -> EnqueueTaskResult:
        result = await self._repository.enqueue_with_dispatch(execution, payload)
        for superseded in result.superseded:
            # Best effort only. DB state + atomic claim remain the correctness gates.
            try:
                self._transport.revoke(task_id=superseded.task_id, terminate=False)
            except Exception:
                continue
        return result
