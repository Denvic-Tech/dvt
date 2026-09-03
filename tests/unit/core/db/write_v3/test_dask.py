from __future__ import annotations

import threading

import dask.dataframe as dd
import pandas as pd

from core.db.write_v3.dask import process_partitions_bounded


def test_process_partitions_bounded_runs_upstream_callbacks_once() -> None:
    base = dd.from_pandas(pd.DataFrame({"value": [1, 2, 3, 4]}), npartitions=2)
    events = {"start": 0, "end": 0, "partitions": []}
    event_lock = threading.Lock()

    def on_start(_meta, operation_id: str) -> None:
        assert operation_id == "write_v3_test_operation"
        with event_lock:
            events["start"] += 1

    def on_end(_meta, operation_id: str) -> None:
        assert operation_id == "write_v3_test_operation"
        with event_lock:
            events["end"] += 1

    def on_partition(_partition, operation_id: str, partition_info: dict[str, object]) -> None:
        assert operation_id == "write_v3_test_operation"
        with event_lock:
            events["partitions"].append(partition_info["number"])

    ddf = base.add_callbacks(
        on_start=on_start,
        on_end=on_end,
        on_partition=on_partition,
        operation_id="write_v3_test_operation",
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
