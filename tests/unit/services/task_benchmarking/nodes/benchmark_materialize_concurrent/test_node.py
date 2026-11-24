import dask.dataframe as dd
import pandas as pd

from services.task_benchmarking import metrics
from services.task_benchmarking.nodes.benchmark_materialize import BenchmarkMaterialize
from services.task_benchmarking.nodes.benchmark_materialize_concurrent import (
    BenchmarkMaterializeConcurrent,
)

_NODE_KWARGS = {"user_id": "user-1", "project_id": "project-1", "task_id": "task-1"}


async def _single(df: dd.DataFrame, **inputs) -> dict:
    metrics.reset()
    await BenchmarkMaterialize(**_NODE_KWARGS, node_id="single", df=df, **inputs).process()
    return metrics.get_metrics()["single"]


async def test_concurrent_sink_matches_two_separate_sinks() -> None:
    shared = dd.from_pandas(pd.DataFrame({"v": range(20), "w": [0.5] * 20}), npartitions=4)
    branch_a = shared[shared.v % 2 == 0].sort_values("v", ascending=False).sort_values("v")
    branch_b = shared.assign(x=shared.v * 3)
    expected_a = await _single(branch_a, mode="checksum", num_workers=2, sorted_by="v")
    expected_b = await _single(branch_b, mode="checksum", num_workers=2)
    metrics.reset()

    await BenchmarkMaterializeConcurrent(
        **_NODE_KWARGS,
        node_id="pair",
        df=branch_a,
        df_b=branch_b,
        mode="checksum",
        num_workers=2,
        sorted_by="v",
    ).process()

    recorded = metrics.get_metrics()["pair"]
    assert recorded["rows"] == 30
    assert recorded["rows_a"] == expected_a["rows"] == 10
    assert recorded["checksum_a"] == expected_a["checksum"]
    assert recorded["sorted_ok_a"] is expected_a["sorted_ok"] is True
    assert recorded["rows_b"] == expected_b["rows"] == 20
    assert recorded["checksum_b"] == expected_b["checksum"]
    assert "sorted_ok_b" not in recorded


async def test_concurrent_sink_counts_rows_with_sync_scheduler() -> None:
    metrics.reset()
    frame = dd.from_pandas(pd.DataFrame({"v": range(7)}), npartitions=2)

    await BenchmarkMaterializeConcurrent(
        **_NODE_KWARGS, node_id="pair", df=frame, df_b=frame[frame.v > 2], num_workers=1
    ).process()

    assert metrics.get_metrics()["pair"] == {
        "rows": 11,
        "rows_a": 7,
        "rows_b": 4,
        "mode": "count_rows",
        "num_workers": 1,
    }
