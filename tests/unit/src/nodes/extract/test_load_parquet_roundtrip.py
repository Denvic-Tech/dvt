from __future__ import annotations

import dask.dataframe as dd
import fsspec
import pandas as pd
import pytest

from core.parquet.write import ParquetWriteRequest, write_dataframe
from core.types import FsCtx

from src.nodes.extract.load_parquet import LoadParquet


def _memory_context(fs, path: str) -> FsCtx:
    return FsCtx(
        fs=fs,
        protocol="memory",
        path=f"memory://bucket/{path}",
        storage_options={},
    )


def _load(ctx: FsCtx, path: str, monkeypatch) -> pd.DataFrame:
    node = LoadParquet(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-parquet-node",
        connection=object(),
        path=path,
        usecols=None,
    )
    monkeypatch.setattr(node, "_get_fs_context", lambda **_kwargs: ctx)
    result = node._read_parquet().compute()
    if "id" in result.columns:
        return result.sort_values("id").reset_index(drop=True)
    return result


@pytest.mark.parametrize(
    "partition_values",
    [
        pd.Series(["001", "00001", "true", "false", "1.5"], dtype="string"),
        pd.Series([1, 2, 1, 3], dtype="int64"),
        pd.Series([1.5, 2.5, 1.5, 3.5], dtype="float64"),
        pd.Series([True, False, True], dtype="bool"),
        pd.Series(
            [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")],
            dtype="datetime64[us]",
        ),
        pd.Series(["001", None, "true"], dtype="string"),
    ],
)
def test_save_new_partitioned_load_parquet_round_trip_preserves_values_and_dtype(
    partition_values,
    monkeypatch,
):
    fs = fsspec.filesystem("memory")
    fs.store.clear()
    path = "partitioned"
    ctx = _memory_context(fs, path)
    expected = pd.DataFrame(
        {
            "id": range(len(partition_values)),
            "part": partition_values,
        }
    )

    write_dataframe(
        dd.from_pandas(expected, npartitions=2),
        ctx,
        ParquetWriteRequest(
            path=path,
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["part"],
        ),
    )

    actual = _load(ctx, path, monkeypatch)
    pd.testing.assert_series_equal(actual["part"], expected["part"], check_names=False)
    assert actual["id"].tolist() == expected["id"].tolist()


def test_save_new_round_trip_simple_row_cap_uuid_append_and_parquet_types(monkeypatch):
    fs = fsspec.filesystem("memory")
    fs.store.clear()

    simple_ctx = _memory_context(fs, "simple.parquet")
    simple = pd.DataFrame({"id": [1, 2], "value": ["a", "b"]})
    write_dataframe(
        dd.from_pandas(simple, npartitions=2),
        simple_ctx,
        ParquetWriteRequest(
            path="simple.parquet",
            mode="create",
            parquet_types={"id": "int64", "value": "large_string"},
        ),
    )
    simple_actual = _load(simple_ctx, "simple.parquet", monkeypatch)
    assert simple_actual.to_dict(orient="records") == simple.to_dict(orient="records")
    assert simple_actual["id"].dtype == "int64"
    assert str(simple_actual["value"].dtype).startswith("string")

    advanced_ctx = _memory_context(fs, "advanced")
    first = pd.DataFrame({"id": [1, 2, 3], "value": ["a", "b", "c"]})
    write_dataframe(
        dd.from_pandas(first, npartitions=2),
        advanced_ctx,
        ParquetWriteRequest(
            path="advanced",
            mode="create",
            filename_template="<uuid>.parquet",
            row_cap=1,
        ),
    )
    write_dataframe(
        dd.from_pandas(pd.DataFrame({"id": [4], "value": ["d"]}), npartitions=1),
        advanced_ctx,
        ParquetWriteRequest(
            path="advanced",
            mode="append",
            filename_template="<uuid>.parquet",
            row_cap=1,
        ),
    )
    actual = _load(advanced_ctx, "advanced", monkeypatch)
    assert actual.to_dict(orient="records") == [
        {"id": 1, "value": "a"},
        {"id": 2, "value": "b"},
        {"id": 3, "value": "c"},
        {"id": 4, "value": "d"},
    ]


def test_save_new_load_round_trip_preserves_unnamed_index_with_reserved_column(monkeypatch):
    fs = fsspec.filesystem("memory")
    fs.store.clear()
    ctx = _memory_context(fs, "indexed.parquet")
    expected = pd.DataFrame(
        {"__index_level_0__": [10, 20]},
        index=pd.Index([5, 6], name=None),
    )

    write_dataframe(
        dd.from_pandas(expected, npartitions=2),
        ctx,
        ParquetWriteRequest(
            path="indexed.parquet",
            mode="create",
            write_index=True,
        ),
    )

    actual = _load(ctx, "indexed.parquet", monkeypatch)
    assert actual["__index_level_0__"].tolist() == [10, 20]
    assert actual.index.tolist() == [5, 6]
    assert actual.index.name is None
