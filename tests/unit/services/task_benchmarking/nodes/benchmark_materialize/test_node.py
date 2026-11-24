import dask.dataframe as dd
import numpy as np
import pandas as pd
import pytest

from services.task_benchmarking import metrics
from services.task_benchmarking.nodes.benchmark_materialize import BenchmarkMaterialize
from services.task_benchmarking.nodes.benchmark_materialize.node import _exact_int_sum


def _make_node(**inputs) -> BenchmarkMaterialize:
    return BenchmarkMaterialize(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="materialize",
        df=dd.from_pandas(pd.DataFrame({"value": range(10)}), npartitions=3),
        **inputs,
    )


@pytest.mark.parametrize("num_workers", [1, 2])
async def test_count_rows_records_row_count(num_workers: int) -> None:
    metrics.reset()

    await _make_node(num_workers=num_workers).process()

    assert metrics.get_metrics()["materialize"] == {
        "rows": 10,
        "mode": "count_rows",
        "num_workers": num_workers,
    }


async def test_full_pandas_records_rows_and_pandas_bytes() -> None:
    metrics.reset()

    await _make_node(mode="full_pandas", num_workers=2).process()

    recorded = metrics.get_metrics()["materialize"]
    assert recorded["rows"] == 10
    assert recorded["mode"] == "full_pandas"
    assert recorded["pandas_bytes"] > 0


def _checksum_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "i": pd.array([1, None, 3, 4], dtype="Int64"),
            "f": [0.5, 1.5, float("nan"), 2.0],
            "b": [True, False, True, True],
            "s": pd.array(["ab", None, "cde", "f"], dtype="string"),
            "t": pd.to_datetime(["1970-01-01 00:00:01.900", None, "1970-01-01 00:00:10.000", None]),
        }
    )


async def test_checksum_records_counts_and_type_specific_sums() -> None:
    metrics.reset()
    node = _make_node(mode="checksum", num_workers=2)
    node.df = dd.from_pandas(_checksum_frame(), npartitions=2)

    await node.process()

    recorded = metrics.get_metrics()["materialize"]
    assert recorded["rows"] == 4
    assert recorded["checksum"] == {
        "i": {"count": 3, "sum": 8},
        "f": {"count": 3, "sum": 4.0},
        "b": {"count": 4, "sum": 3},
        "s": {"count": 3, "sum": 6},
        "t": {"count": 2, "sum": 11},
    }
    assert "sorted_ok" not in recorded


def test_checksum_int_sum_is_exact_beyond_int64_range() -> None:
    values = np.full(3, 2**62, dtype="int64")

    assert _exact_int_sum(values) == 3 * 2**62


@pytest.mark.parametrize(
    ("values", "expected"),
    [([1, 2, 3, 4, 5, 6], True), ([1, 2, 4, 3, 5, 6], False), ([1, 2, 5, 3, 4, 6], False)],
)
async def test_checksum_sorted_by_checks_each_partition_and_partition_bounds(
    values: list[int], expected: bool
) -> None:
    metrics.reset()
    node = _make_node(mode="checksum", sorted_by="value")
    node.df = dd.from_pandas(pd.DataFrame({"value": values}), npartitions=3, sort=False)

    await node.process()

    assert metrics.get_metrics()["materialize"]["sorted_ok"] is expected
