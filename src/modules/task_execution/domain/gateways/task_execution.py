from collections.abc import Mapping
from typing import Protocol

from ..entities import NestedWaitReservation


class TaskTransport(Protocol):
    """Delivery transport.  Celery is one implementation, not a flow dependency."""

    def publish(self, *, task_id: str, payload: Mapping[str, object]) -> None: ...

    def revoke(self, *, task_id: str, terminate: bool = False) -> None: ...


class TaskCancellationGateway(Protocol):
    """Low-latency cancellation transport with PostgreSQL as its source of truth."""

    async def notify_stop(self, *, task_id: str) -> None: ...

    async def get_stop_reason(self, *, task_id: str) -> str | None: ...

    async def wait_for_stop(self, *, task_id: str) -> str: ...


class NestedWaitReservationGateway(Protocol):
    """Storage for synchronous nested-wait reservations."""

    async def list(self) -> tuple[NestedWaitReservation, ...]: ...

    async def get(self, *, parent_task_id: str) -> NestedWaitReservation | None: ...

    async def reserve(
        self,
        reservation: NestedWaitReservation,
        *,
        max_waiters: int,
    ) -> bool: ...

    async def rebalance(self, *, max_waiters: int) -> tuple[NestedWaitReservation, ...]: ...

    async def release_by_parent(self, *, parent_task_id: str) -> None: ...

    async def release_by_child(self, *, child_task_id: str) -> None: ...

    async def release_by_worker(self, *, worker_id: str) -> None: ...
