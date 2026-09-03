from collections.abc import Collection

from ...domain.entities import NestedWaitDecision, NestedWaitReservation
from ...domain.gateways import NestedWaitReservationGateway
from ...domain.policies import decide_nested_wait_reservation


class ReserveNestedWaitUseCase:
    def __init__(self, gateway: NestedWaitReservationGateway) -> None:
        self._gateway = gateway

    async def execute(
        self,
        *,
        parent_task_id: str,
        child_task_id: str,
        origin_worker_id: str,
        alive_worker_ids: Collection[str],
    ) -> NestedWaitDecision:
        existing = await self._gateway.get(parent_task_id=parent_task_id)
        if existing is not None:
            if (
                existing.child_task_id == child_task_id
                and existing.origin_worker_id == origin_worker_id
            ):
                return NestedWaitDecision(accepted=True)
            return NestedWaitDecision(
                accepted=False,
                error=f"Parent task {parent_task_id} already owns another nested wait reservation.",
            )

        reservations = await self._gateway.list()
        decision = decide_nested_wait_reservation(
            origin_worker_id=origin_worker_id,
            alive_worker_ids=alive_worker_ids,
            reserved_origin_worker_ids=[item.origin_worker_id for item in reservations],
        )
        if not decision.accepted:
            return decision

        alive_count = len(set(alive_worker_ids))
        reserved = await self._gateway.reserve(
            NestedWaitReservation(
                parent_task_id=parent_task_id,
                child_task_id=child_task_id,
                origin_worker_id=origin_worker_id,
            ),
            max_waiters=max(alive_count - 1, 0),
        )
        if reserved:
            return NestedWaitDecision(accepted=True)

        return NestedWaitDecision(
            accepted=False,
            error=(
                "Nested wait rejected to prevent distributed deadlock: "
                "another parent reserved the remaining execution capacity concurrently."
            ),
        )


class ReleaseNestedWaitUseCase:
    def __init__(self, gateway: NestedWaitReservationGateway) -> None:
        self._gateway = gateway

    async def execute(
        self,
        *,
        parent_task_id: str | None = None,
        child_task_id: str | None = None,
        worker_id: str | None = None,
    ) -> None:
        if parent_task_id is not None:
            await self._gateway.release_by_parent(parent_task_id=parent_task_id)
        if child_task_id is not None:
            await self._gateway.release_by_child(child_task_id=child_task_id)
        if worker_id is not None:
            await self._gateway.release_by_worker(worker_id=worker_id)
