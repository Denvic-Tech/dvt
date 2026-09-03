from ...domain.entities import TaskExecution
from ...domain.gateways import TaskCancellationGateway, TaskTransport
from ...domain.repositories import TaskExecutionRepository
from ...domain.types import TaskExecutionStatus, TaskTerminationReason


class RequestStopUseCase:
    """Persist cooperative STOP and wake/revoke transport as appropriate."""

    def __init__(
        self,
        repository: TaskExecutionRepository,
        cancellation: TaskCancellationGateway,
        transport: TaskTransport,
    ) -> None:
        self._repository = repository
        self._cancellation = cancellation
        self._transport = transport

    async def execute(
        self,
        *,
        task_id: str,
        reason: TaskTerminationReason,
    ) -> TaskExecution | None:
        task = await self._repository.request_stop(task_id=task_id, reason=reason, hard=False)
        if task is None:
            return None
        if task.status == TaskExecutionStatus.CANCEL_REQUESTED:
            await self._cancellation.notify_stop(task_id=task_id)
        elif task.status == TaskExecutionStatus.CANCELLED and task.termination_reason == reason:
            self._transport.revoke(task_id=task_id, terminate=False)
        return task
