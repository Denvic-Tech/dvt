"""Cooperative cancellation shared by nodes and local delayed work."""
from collections.abc import Callable
from dataclasses import dataclass

from .exceptions import NodeExecutionCancelled


@dataclass(frozen=True)
class CancellationToken:
    """Read-only task signal; safe to capture in local threaded Dask work.

    A default token never requests cancellation. Tokens bound to a task are
    process-local and must not be sent to distributed/process schedulers.
    """

    _is_requested: Callable[[], bool] | None = None

    def is_requested(self) -> bool:
        return self._is_requested is not None and self._is_requested()

    def raise_if_requested(self) -> None:
        if self.is_requested():
            raise NodeExecutionCancelled("Task stop requested")
