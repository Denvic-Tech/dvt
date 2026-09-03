from __future__ import annotations

import uuid
from pathlib import Path

import dask.dataframe as dd
import fsspec
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from core.parquet.write import ParquetWriteRequest, write_dataframe
from core.types import FsCtx

from src.nodes.extract.load_parquet import LoadParquet


def _ctx(path: Path) -> FsCtx:
    return FsCtx(fs=fsspec.filesystem("file"), protocol="file", path=str(path), storage_options={})


def _load(ctx: FsCtx, logical_path: str, monkeypatch) -> pd.DataFrame:
    node = LoadParquet(
        user_id="integration-user",
        project_id="integration-project",
        task_id="integration-task",
        node_id="load-parquet-node",
        connection=object(),
        path=logical_path,
        usecols=None,
    )
    monkeypatch.setattr(node, "_get_fs_context", lambda **_kwargs: ctx)
    result = node._read_parquet().compute()
    if "id" in result.columns:
        result = result.sort_values("id").reset_index(drop=True)
    return result


def _assert_no_sidecars_or_parquet_directories(root: Path) -> None:
    assert not list(root.rglob("_metadata"))
    assert not list(root.rglob("_common_metadata"))
    assert not any(path.is_dir() and path.name.endswith(".parquet") for path in root.rglob("*"))


def test_write_v1_real_filesystem_roundtrip_layouts(tmp_path: Path, monkeypatch) -> None:
    pdf = pd.DataFrame({"id": range(7), "country": ["RU", "US", "DE", "RU", "US", "DE", "RU"]})
    ddf = dd.from_pandas(pdf, npartitions=3)

    simple_path = tmp_path / "export" / "data.parquet"
    simple_ctx = _ctx(simple_path)
    write_dataframe(ddf, simple_ctx, ParquetWriteRequest(path="export/data.parquet", mode="create"))
    assert simple_path.is_file()
    pd.testing.assert_frame_equal(
        _load(simple_ctx, "export/data.parquet", monkeypatch), pdf, check_dtype=False
    )

    increment_path = tmp_path / "export" / "increment"
    increment_ctx = _ctx(increment_path)
    write_dataframe(
        ddf,
        increment_ctx,
        ParquetWriteRequest(
            path="export/increment", mode="create", filename_template="<increment>.parquet"
        ),
    )
    assert sorted(path.name for path in increment_path.glob("*.parquet")) == [
        "00000.parquet",
        "00001.parquet",
        "00002.parquet",
    ]
    pd.testing.assert_frame_equal(
        _load(increment_ctx, "export/increment", monkeypatch), pdf, check_dtype=False
    )

    uuid_path = tmp_path / "export" / "uuid"
    uuid_ctx = _ctx(uuid_path)
    write_dataframe(
        ddf,
        uuid_ctx,
        ParquetWriteRequest(path="export/uuid", mode="create", filename_template="<uuid>.parquet"),
    )
    uuid_names = [path.stem for path in uuid_path.glob("*.parquet")]
    assert len(uuid_names) == 3
    assert all(uuid.UUID(name).version == 4 for name in uuid_names)

    capped_path = tmp_path / "export" / "capped"
    capped_ctx = _ctx(capped_path)
    write_dataframe(
        ddf,
        capped_ctx,
        ParquetWriteRequest(
            path="export/capped",
            mode="create",
            filename_template="<increment>.parquet",
            row_cap=2,
        ),
    )
    capped_files = sorted(capped_path.glob("*.parquet"))
    assert len(capped_files) == 4
    assert all(pq.read_table(path).num_rows <= 2 for path in capped_files)

    partitioned_path = tmp_path / "export" / "partitioned"
    partitioned_ctx = _ctx(partitioned_path)
    write_dataframe(
        ddf,
        partitioned_ctx,
        ParquetWriteRequest(
            path="export/partitioned",
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["country"],
        ),
    )
    actual_partitioned = _load(partitioned_ctx, "export/partitioned", monkeypatch)
    pd.testing.assert_frame_equal(actual_partitioned, pdf, check_dtype=False)

    _assert_no_sidecars_or_parquet_directories(tmp_path)


def test_write_v1_partition_all_columns_and_empty_partitioned_roundtrip(
    tmp_path: Path, monkeypatch
) -> None:
    all_partitioned_path = tmp_path / "export" / "all-partitioned"
    all_partitioned_ctx = _ctx(all_partitioned_path)
    pdf = pd.DataFrame({"country": ["RU", "RU", "US"]})
    result = write_dataframe(
        dd.from_pandas(pdf, npartitions=1),
        all_partitioned_ctx,
        ParquetWriteRequest(
            path="export/all-partitioned",
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["country"],
            row_cap=1,
        ),
    )
    assert result.rows_written == len(pdf)
    actual = _load(all_partitioned_ctx, "export/all-partitioned", monkeypatch)
    assert sorted(actual["country"].astype(str).tolist()) == ["RU", "RU", "US"]

    empty_path = tmp_path / "export" / "empty-partitioned"
    empty_ctx = _ctx(empty_path)
    empty = pd.DataFrame(
        {
            "id": pd.Series(dtype="int64"),
            "country": pd.Series(dtype="string"),
        }
    )
    empty_result = write_dataframe(
        dd.from_pandas(empty, npartitions=1),
        empty_ctx,
        ParquetWriteRequest(
            path="export/empty-partitioned",
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["country"],
        ),
    )
    assert empty_result.rows_written == 0
    assert empty_result.files_written == 1
    assert _load(empty_ctx, "export/empty-partitioned", monkeypatch).empty

    appended = pd.DataFrame({"id": [1, 2], "country": ["RU", "US"]})
    write_dataframe(
        dd.from_pandas(appended, npartitions=1),
        empty_ctx,
        ParquetWriteRequest(
            path="export/empty-partitioned",
            mode="append",
            filename_template="<increment>.parquet",
            partition_on=["country"],
        ),
    )
    actual_appended = _load(empty_ctx, "export/empty-partitioned", monkeypatch)
    actual_appended["country"] = actual_appended["country"].astype(str)
    pd.testing.assert_frame_equal(
        actual_appended.sort_values("id").reset_index(drop=True),
        appended,
        check_dtype=False,
    )
    _assert_no_sidecars_or_parquet_directories(tmp_path)


def test_write_v1_partition_type_category_null_and_reserved_sentinel(
    tmp_path: Path, monkeypatch
) -> None:
    typed_path = tmp_path / "export" / "typed-partition"
    typed_ctx = _ctx(typed_path)
    valid = pd.DataFrame({"id": [1, 2], "part": ["001", "2"]})
    write_dataframe(
        dd.from_pandas(valid, npartitions=1),
        typed_ctx,
        ParquetWriteRequest(
            path="export/typed-partition",
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["part"],
            parquet_types={"part": "int64"},
        ),
    )
    actual_typed = _load(typed_ctx, "export/typed-partition", monkeypatch)
    assert sorted(actual_typed["part"].tolist()) == [1, 2]

    bad_path = tmp_path / "export" / "bad-partition"
    with pytest.raises(ValueError, match=r"Cannot write Hive partition value 'abc'.*int64"):
        write_dataframe(
            dd.from_pandas(pd.DataFrame({"id": [1], "part": ["abc"]}), npartitions=1),
            _ctx(bad_path),
            ParquetWriteRequest(
                path="export/bad-partition",
                mode="create",
                filename_template="<increment>.parquet",
                partition_on=["part"],
                parquet_types={"part": "int64"},
            ),
        )
    if bad_path.exists():
        assert not list(bad_path.rglob("*.parquet"))

    category_path = tmp_path / "export" / "category"
    category_ctx = _ctx(category_path)
    category_pdf = pd.DataFrame(
        {
            "id": [1, 2, 3, 4],
            "category": pd.Categorical(["RU", "US", "RU", None]),
        }
    )
    write_dataframe(
        dd.from_pandas(category_pdf, npartitions=2),
        category_ctx,
        ParquetWriteRequest(
            path="export/category",
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["category"],
        ),
    )
    category_actual = _load(category_ctx, "export/category", monkeypatch).sort_values("id")
    assert str(category_actual["category"].dtype) == "category"
    assert (
        category_actual["category"]
        .astype(object)
        .where(category_actual["category"].notna(), None)
        .tolist()
        == ["RU", "US", "RU", None]
    )

    category_append = pd.DataFrame(
        {"id": [5], "category": pd.Categorical(["DE"], categories=["DE"])}
    )
    write_dataframe(
        dd.from_pandas(category_append, npartitions=1),
        category_ctx,
        ParquetWriteRequest(
            path="export/category",
            mode="append",
            filename_template="<increment>.parquet",
            partition_on=["category"],
        ),
    )
    appended_category = _load(category_ctx, "export/category", monkeypatch).sort_values("id")
    assert str(appended_category["category"].dtype) == "category"
    assert set(appended_category["category"].cat.categories) == {"RU", "US", "DE"}
    assert appended_category.iloc[-1]["category"] == "DE"

    mixed_path = tmp_path / "export" / "mixed-category"
    mixed_ctx = _ctx(mixed_path)
    mixed_pdf = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "category": pd.Categorical(["A", "B", "A"]),
            "region": ["EU", "US", "US"],
        }
    )
    write_dataframe(
        dd.from_pandas(mixed_pdf, npartitions=1),
        mixed_ctx,
        ParquetWriteRequest(
            path="export/mixed-category",
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["category", "region"],
        ),
    )
    mixed_actual = _load(mixed_ctx, "export/mixed-category", monkeypatch).sort_values("id")
    assert str(mixed_actual["category"].dtype) == "category"
    pd.testing.assert_frame_equal(mixed_actual, mixed_pdf, check_dtype=False)

    sentinel_path = tmp_path / "export" / "sentinel"
    with pytest.raises(ValueError, match="reserved for NULL values"):
        write_dataframe(
            dd.from_pandas(
                pd.DataFrame(
                    {"id": [1, 2], "part": ["__HIVE_DEFAULT_PARTITION__", None]}
                ),
                npartitions=1,
            ),
            _ctx(sentinel_path),
            ParquetWriteRequest(
                path="export/sentinel",
                mode="create",
                filename_template="<increment>.parquet",
                partition_on=["part"],
            ),
        )
    if sentinel_path.exists():
        assert not list(sentinel_path.rglob("*.parquet"))


def test_write_v1_real_filesystem_append_and_preflight_failures(tmp_path: Path, monkeypatch) -> None:
    dataset_path = tmp_path / "export" / "append"
    ctx = _ctx(dataset_path)
    first = pd.DataFrame({"id": [1]})
    write_dataframe(
        dd.from_pandas(first, npartitions=1),
        ctx,
        ParquetWriteRequest(
            path="export/append", mode="create", filename_template="<increment>.parquet"
        ),
    )
    for name in ("00002.parquet", "00003.parquet"):
        pq.write_table(pa.Table.from_pandas(first, preserve_index=False), dataset_path / name)

    write_dataframe(
        dd.from_pandas(pd.DataFrame({"id": [4]}), npartitions=1),
        ctx,
        ParquetWriteRequest(
            path="export/append", mode="append", filename_template="<increment>.parquet"
        ),
    )
    assert (dataset_path / "00004.parquet").is_file()
    assert sorted(_load(ctx, "export/append", monkeypatch)["id"].tolist()) == [1, 1, 1, 4]

    non_empty_path = tmp_path / "export" / "non-empty"
    non_empty_path.mkdir(parents=True)
    existing = non_empty_path / "keep.txt"
    existing.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError, match="not empty"):
        write_dataframe(
            dd.from_pandas(pd.DataFrame({"id": [2]}), npartitions=1),
            _ctx(non_empty_path),
            ParquetWriteRequest(
                path="export/non-empty", mode="create", filename_template="<increment>.parquet"
            ),
        )
    assert existing.read_text(encoding="utf-8") == "keep"
    assert list(non_empty_path.iterdir()) == [existing]

    before = sorted(path.relative_to(dataset_path) for path in dataset_path.rglob("*"))
    with pytest.raises(ValueError, match="schema does not match"):
        write_dataframe(
            dd.from_pandas(pd.DataFrame({"id": ["wrong"]}), npartitions=1),
            ctx,
            ParquetWriteRequest(
                path="export/append", mode="append", filename_template="<increment>.parquet"
            ),
        )
    after = sorted(path.relative_to(dataset_path) for path in dataset_path.rglob("*"))
    assert after == before
    _assert_no_sidecars_or_parquet_directories(tmp_path)
