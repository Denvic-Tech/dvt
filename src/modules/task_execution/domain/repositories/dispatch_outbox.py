from collections.abc import Sequence
from typing import Protocol

from ..entities import DispatchOutboxItem


class DispatchOutbox(Protocol):
    """Focused contract for durable execution-message delivery."""

    async def pending_dispatches(self, *, limit: int) -> Sequence[DispatchOutboxItem]: ...

    async def mark_dispatch_published(self, *, dispatch_id: str) -> None: ...

    async def record_dispatch_failure(self, *, dispatch_id: str, error: str) -> None: ...
