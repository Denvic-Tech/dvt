from ...domain.gateways import TaskTransport
from ...domain.repositories import DispatchOutbox


class PublishPendingDispatchesUseCase:
    def __init__(self, repository: DispatchOutbox, transport: TaskTransport) -> None:
        self._repository = repository
        self._transport = transport

    async def execute(self, *, limit: int = 100) -> int:
        published = 0
        for dispatch in await self._repository.pending_dispatches(limit=limit):
            try:
                self._transport.publish(task_id=dispatch.task_id, payload=dispatch.payload)
            except Exception as exc:
                await self._repository.record_dispatch_failure(
                    dispatch_id=dispatch.dispatch_id,
                    error=str(exc),
                )
                continue
            # A crash before this commit can publish a duplicate.  Claim is the dedupe gate.
            await self._repository.mark_dispatch_published(dispatch_id=dispatch.dispatch_id)
            published += 1
        return published
