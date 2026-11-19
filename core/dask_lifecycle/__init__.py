"""The single place in DVT that knows how node-output lifecycle events come out of Dask.

DVT attaches lifecycle handlers to lazily built Dask DataFrame outputs and hears when an output
starts, produces each partition, ends or fails while some downstream computation runs. The
events come from a pass-through tap in the graph plus a stock ``dask.callbacks.Callback`` (see
``core.dask_lifecycle.tap`` for the rules).

Importing this package also switches Dask's ``tune`` optimizer stage off by default in this
process (``optimization.tune.active``), so graphs run with the partitioning they declare when
they are built: ``tune`` would otherwise re-plan groupby ``split_out`` and merge small input
partitions of column-projected reads at compute time. Code that wants ``tune`` sets the key
back with ``dask.config.set``; node outputs keep their declared partitioning either way.
"""

import dask

from core.dask_lifecycle.handlers import OutputLifecycleHandlers
from core.dask_lifecycle.tap import (
    attach_lifecycle,
    delayed_partitions,
    suppress_lifecycle_events,
)

__all__ = [
    "OutputLifecycleHandlers",
    "attach_lifecycle",
    "delayed_partitions",
    "suppress_lifecycle_events",
]

dask.config.update_defaults({"optimization": {"tune": {"active": False}}})
