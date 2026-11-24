from __future__ import annotations

from collections.abc import Iterable
from pathlib import PurePath

import dask
import dask.dataframe as dd

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


def compute_once(*tasks, max_workers: int):
    """Execute all tasks as one coherent Dask computation.

    Keeping one scheduler session is important: shared upstream dependencies are then
    computed once and reused by every downstream partition/write task. Node lifecycle events of
    the upstream outputs are reported by this run too (see ``core.dask_lifecycle``).
    """
    workers = max(1, int(max_workers))
    return dask.compute(
        *tasks,
        scheduler="threads" if workers > 1 else "sync",
        num_workers=workers,
    )


def _iter_path_values(value: object) -> Iterable[str]:
    if isinstance(value, (str, PurePath)):
        yield str(value)
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _iter_path_values(item)
