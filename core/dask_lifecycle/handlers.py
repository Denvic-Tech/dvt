from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class OutputLifecycleHandlers:
    """What DVT wants to hear about one lazily computed DataFrame output.

    ``on_start`` - the output began to be produced; ``on_end`` - every partition of the output
    was produced (``on_partition`` has returned for each of them); ``on_error`` - the computation
    producing the output failed after it had started and before it ended. ``on_partition``
    receives each produced partition and its number (``None`` when Dask did not report one).
    """

    on_start: Callable[[], None] | None = None
    on_end: Callable[[], None] | None = None
    on_error: Callable[[], None] | None = None
    on_partition: Callable[[Any, int | None], None] | None = None

    def is_empty(self) -> bool:
        return (
            self.on_start is None
            and self.on_end is None
            and self.on_error is None
            and self.on_partition is None
        )
