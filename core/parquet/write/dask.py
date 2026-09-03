from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import PurePath

import dask
import dask.dataframe as dd
from dask.callbacks import Callback
from dask.dataframe.dask_expr._collection import _collect_public_operation_callbacks_specs
from dask.dataframe.dask_expr._operation_callbacks import PublicOperationCallbacks

_DVT_SOURCE_PATH_ARG = "__dvt_source_path_arg__"


def mark_source_path_arg(index: int = 0):
    """Mark a delayed reader function argument as a filesystem source path.

    DVT readers that do not produce a native Dask ``ReadParquet`` expression can
    opt into overwrite-safety provenance without coupling the writer to a
    concrete node implementation.
    """

    def decorator(func):
        setattr(func, _DVT_SOURCE_PATH_ARG, int(index))
        return func

    return decorator


def find_source_paths(ddf: dd.DataFrame) -> tuple[str, ...]:
    """Return known filesystem source paths referenced by a Dask DataFrame graph."""

    paths: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        for path in _iter_path_values(value):
            if path not in seen:
                seen.add(path)
                paths.append(path)

    try:
        from dask.dataframe.dask_expr.io.parquet import ReadParquet

        for operation in ddf.expr.find_operations(ReadParquet):
            add(operation.path)
    except (AttributeError, ImportError, TypeError):
        # Dask expression internals are version-specific. Explicit DVT provenance
        # below remains available even when native ReadParquet introspection is not.
        pass

    graph = ddf.__dask_graph__()
    values: Iterable[object] = graph.values() if hasattr(graph, "values") else ()
    for task in values:
        func = getattr(task, "func", None)
        source_arg = getattr(func, _DVT_SOURCE_PATH_ARG, None)
        if source_arg is None:
            continue
        args = getattr(task, "args", ())
        try:
            add(args[int(source_arg)])
        except (IndexError, TypeError, ValueError):
            continue

    return tuple(paths)


def flatten_delayed_partitions(ddf: dd.DataFrame) -> list:
    delayed = ddf.to_delayed()
    if hasattr(delayed, "ravel"):
        return list(delayed.ravel())
    return list(delayed)


def compute_once(*tasks, max_workers: int):
    """Execute all tasks as one coherent Dask computation.

    Keeping one scheduler session is important: shared upstream dependencies are then
    computed once and reused by every downstream partition/write task.
    """
    workers = max(1, int(max_workers))
    return dask.compute(
        *tasks,
        scheduler="threads" if workers > 1 else "sync",
        num_workers=workers,
    )


@contextmanager
def dataframe_operation_callbacks(ddf: dd.DataFrame):
    """Activate DVT-Dask public operation callbacks for a non-Frame compute entrypoint.

    ``FrameBase.compute`` normally installs this context itself. SaveParquet intentionally
    executes delayed write tasks with one ``dask.compute`` so Simple ordering and shared
    upstream reuse are preserved, therefore it must bridge the callback lifecycle here.

    The DVT-Dask integration is deliberately isolated in this module because these imports
    are version-specific internals of the pinned ``dvt-dask`` package.
    """
    callback_specs = _collect_public_operation_callbacks_specs(ddf)
    if not callback_specs or _has_active_public_operation_callbacks(callback_specs):
        yield
        return

    with PublicOperationCallbacks(callback_specs):
        yield


def compute_with_dataframe_callbacks(
        ddf: dd.DataFrame,
        *tasks,
        max_workers: int,
):
    """Run delayed tasks once while honoring callbacks attached to ``ddf``."""
    with dataframe_operation_callbacks(ddf):
        return compute_once(*tasks, max_workers=max_workers)


def _has_active_public_operation_callbacks(callback_specs) -> bool:
    """Return whether one active DVT-Dask callback bridge already covers all specs.

    ``Callback.active`` stores callback method tuples, not callback instances. Recovering
    their bound owner lets us avoid creating a nested ``PublicOperationCallbacks`` context,
    which would otherwise emit every lifecycle event twice.
    """
    required = {spec.operation_id: spec.conflict_key() for spec in callback_specs}
    seen_owners: set[int] = set()

    for callback_tuple in tuple(Callback.active):
        for callback in callback_tuple:
            owner = getattr(callback, "__self__", None)
            if not isinstance(owner, PublicOperationCallbacks):
                continue
            owner_id = id(owner)
            if owner_id in seen_owners:
                continue
            seen_owners.add(owner_id)

            active_specs = getattr(owner, "_specs_by_operation_id", {})
            if all(
                    operation_id in active_specs
                    and active_specs[operation_id].conflict_key() == conflict_key
                    for operation_id, conflict_key in required.items()
            ):
                return True

    return False


def _iter_path_values(value: object) -> Iterable[str]:
    if isinstance(value, (str, PurePath)):
        yield str(value)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _iter_path_values(item)
