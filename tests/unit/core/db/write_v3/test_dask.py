from __future__ import annotations

import threading

import dask.dataframe as dd
import pandas as pd
import pytest
from dask.dataframe.dask_expr import _expr as dask_expr

from core.dask_lifecycle import OutputLifecycleHandlers, attach_lifecycle
from core.db.write_v3.dask import process_partitions_bounded


def test_process_partitions_bounded_runs_upstream_callbacks_once() -> None:
    base = dd.from_pandas(pd.DataFrame({"value": [1, 2, 3, 4]}), npartitions=2)
    events = {"start": 0, "end": 0, "partitions": []}
    event_lock = threading.Lock()

    def on_start() -> None:
        with event_lock:
            events["start"] += 1

    def on_end() -> None:
        with event_lock:
            events["end"] += 1

    def on_partition(_partition, part_no: int | None) -> None:
        with event_lock:
            events["partitions"].append(part_no)

    ddf = attach_lifecycle(
        base,
        OutputLifecycleHandlers(
            on_start=on_start,
            on_end=on_end,
            on_partition=on_partition,
        ),
    )

    written = process_partitions_bounded(
        ddf,
        lambda pdf: len(pdf),
        max_workers=2,
    )

    assert written == 4
    assert events["start"] == 1
    assert events["end"] == 1
    assert sorted(events["partitions"]) == [0, 1]


def _recording_handlers(name: str, events: list[tuple], lock: threading.Lock):
    def record(kind: str, part_no: int | None = None) -> None:
        with lock:
            events.append((name, kind, part_no))

    return OutputLifecycleHandlers(
        on_start=lambda: record("start"),
        on_end=lambda: record("end"),
        on_partition=lambda _partition, part_no: record("partition", part_no),
    )


@pytest.mark.parametrize("max_workers", [1, 2])
def test_process_partitions_bounded_does_not_fuse(monkeypatch, max_workers: int) -> None:
    # Blockwise fusion is superlinear on node graphs with a lifecycle tap after every node.
    def fail_fusion(_expr):
        raise AssertionError("the DB write path must not run Dask blockwise fusion")

    monkeypatch.setattr(dask_expr.Expr, "fuse", fail_fusion)
    events: list[tuple] = []
    lock = threading.Lock()

    rows = pd.DataFrame({"key": [0, 1, 2, 3] * 2, "value": range(8)})
    source = attach_lifecycle(
        dd.from_pandas(rows, npartitions=2), _recording_handlers("source", events, lock)
    )
    filtered = attach_lifecycle(
        source[source["value"] >= 2], _recording_handlers("filtered", events, lock)
    )
    labels = dd.from_pandas(pd.DataFrame({"key": [0, 1, 2, 3], "label": list("abcd")}), 1)
    joined = filtered.merge(labels, on="key", how="left")
    ddf = attach_lifecycle(
        dd.concat([joined, filtered]), _recording_handlers("output", events, lock)
    )

    written = process_partitions_bounded(ddf, len, max_workers=max_workers)

    assert written == 12
    for name in ("source", "filtered", "output"):
        kinds = [kind for owner, kind, _ in events if owner == name]
        assert (kinds.count("start"), kinds.count("end")) == (1, 1), name
    source_parts = [n for owner, kind, n in events if owner == "source" and kind == "partition"]
    assert sorted(source_parts) == [0, 1]
