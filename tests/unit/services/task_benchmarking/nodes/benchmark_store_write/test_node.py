import dask.dataframe as dd
import pandas as pd
import pytest

from services.task_benchmarking import metrics, store
from services.task_benchmarking.nodes.benchmark_materialize import BenchmarkMaterialize
from services.task_benchmarking.nodes.benchmark_store_read import BenchmarkStoreRead
from services.task_benchmarking.nodes.benchmark_store_write import BenchmarkStoreWrite

_NODE_KWARGS = {"user_id": "user-1", "project_id": "project-1", "task_id": "task-1"}


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": range(10),
            "i": pd.array([1, None, 3, 4, 5, 6, None, 8, 9, 10], dtype="Int64"),
            "f": [0.5 * n for n in range(10)],
            "s": pd.array(["a", None, "ccc", "d", "ee", "f", "g", None, "i", "jj"], dtype="string"),
            "t": pd.date_range("2024-01-01", periods=10, freq="h"),
        }
    )


async def _checksum(df: dd.DataFrame) -> dict:
    metrics.reset()
    await BenchmarkMaterialize(**_NODE_KWARGS, node_id="sink", df=df, mode="checksum").process()
    return metrics.get_metrics()["sink"]


@pytest.mark.parametrize("fmt", store.FORMATS)
async def test_store_round_trip_keeps_rows_order_and_checksum(tmp_path, fmt: str) -> None:
    source = dd.from_pandas(_frame(), npartitions=3)
    expected = await _checksum(source)
    metrics.reset()

    await BenchmarkStoreWrite(
        **_NODE_KWARGS, node_id="write", df=source, path=str(tmp_path), format=fmt, num_workers=2
    ).process()
    written = metrics.get_metrics()["write"]
    reader = BenchmarkStoreRead(**_NODE_KWARGS, node_id="read", path=str(tmp_path), format=fmt)
    reader.process()

    assert written["rows"] == 10
    assert written["partitions"] == 3
    assert written["store_bytes"] == sum(
        path.stat().st_size for path in store.partition_files(tmp_path, fmt)
    )
    assert reader.output.npartitions == 3
    assert reader.output.compute()["id"].tolist() == list(range(10))
    assert await _checksum(reader.output) == expected


async def test_store_write_replaces_partitions_of_previous_run(tmp_path) -> None:
    store.write_partition(_frame(), store.partition_path(tmp_path, "arrow_ipc", 7), "arrow_ipc", None)
    (tmp_path / "keep.txt").write_text("x")

    await BenchmarkStoreWrite(
        **_NODE_KWARGS,
        node_id="write",
        df=dd.from_pandas(_frame(), npartitions=2),
        path=str(tmp_path),
        format="parquet",
        num_workers=1,
    ).process()

    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "keep.txt",
        "part-00000.parquet",
        "part-00001.parquet",
    ]


def test_store_read_without_partitions_fails(tmp_path) -> None:
    reader = BenchmarkStoreRead(**_NODE_KWARGS, node_id="read", path=str(tmp_path))

    with pytest.raises(FileNotFoundError):
        reader.process()
