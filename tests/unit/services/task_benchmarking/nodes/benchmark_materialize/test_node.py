import dask.dataframe as dd
import pandas as pd
import pytest

from services.task_benchmarking import metrics
from services.task_benchmarking.nodes.benchmark_materialize import BenchmarkMaterialize


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
