from __future__ import annotations

import posixpath
import threading
import uuid

import dask
import dask.dataframe as dd
import fsspec
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from dask.dataframe.dask_expr._collection import _collect_public_operation_callbacks_specs
from dask.dataframe.dask_expr._operation_callbacks import PublicOperationCallbacks

from core.parquet.write import ParquetLayout, ParquetWriteRequest, write_dataframe
from core.parquet.write.filesystem import ParquetFilesystem
from core.parquet.write.naming import FilenameTemplate
from core.parquet.write.schema import read_file_dataset_schema
from core.types import FsCtx

from src.node_dsl.base_node.df_output import (
    DDFPartitionCallbackContext,
    _NodeCallbacksCoordinator,
    _on_operation_end,
    _on_operation_error,
    _on_operation_partition,
    _on_operation_start,
)


def _memory_ctx(fs, path: str) -> FsCtx:
    return FsCtx(
        fs=fs,
        protocol="memory",
        path=f"memory://bucket/{path}",
        storage_options={},
    )


def _protocol_ctx(fs, protocol: str, path: str) -> FsCtx:
    return FsCtx(
        fs=fs,
        protocol=protocol,
        path=f"/bucket/{protocol}/{path}",
        storage_options={},
    )


def _memory_fs():
    fs = fsspec.filesystem("memory")
    fs.store.clear()
    return fs


def _files(fs, root: str = "/bucket") -> list[str]:
    return sorted(fs.find(root))


def test_local_filesystem_exact_simple_and_advanced_layout(tmp_path):
    fs = fsspec.filesystem("file")
    simple_target = tmp_path / "reports" / "orders.parquet"
    simple_ctx = FsCtx(
        fs=fs,
        protocol="file",
        path=str(simple_target),
        storage_options={},
    )
    ddf = dd.from_pandas(pd.DataFrame({"id": range(4)}), npartitions=2)

    write_dataframe(
        ddf,
        simple_ctx,
        ParquetWriteRequest(path="reports/orders.parquet", mode="create"),
    )

    assert simple_target.is_file()
    assert not (simple_target / "orders.parquet").exists()

    advanced_target = tmp_path / "reports" / "dataset"
    advanced_ctx = FsCtx(
        fs=fs,
        protocol="file",
        path=str(advanced_target),
        storage_options={},
    )
    write_dataframe(
        ddf,
        advanced_ctx,
        ParquetWriteRequest(
            path="reports/dataset",
            mode="create",
            filename_template="<increment>.parquet",
        ),
    )

    assert sorted(path.name for path in advanced_target.iterdir()) == [
        "00000.parquet",
        "00001.parquet",
    ]


@pytest.mark.parametrize("protocol", ["memory", "s3", "ftp", "sftp", "smb"])
def test_new_writer_exact_layout_for_supported_fsspec_protocols(protocol):
    fs = _memory_fs()
    ddf = dd.from_pandas(pd.DataFrame({"id": [1, 2, 3]}), npartitions=2)

    write_dataframe(
        ddf,
        _protocol_ctx(fs, protocol, "orders.parquet"),
        ParquetWriteRequest(path="orders.parquet", mode="create"),
    )
    write_dataframe(
        ddf,
        _protocol_ctx(fs, protocol, "orders"),
        ParquetWriteRequest(
            path="orders",
            mode="create",
            filename_template="<increment>.parquet",
        ),
    )

    root = f"/bucket/{protocol}"
    files = sorted(fs.find(root))
    assert f"{root}/orders.parquet" in files
    assert sorted(
        path for path in files if path.startswith(f"{root}/orders/")
    ) == [f"{root}/orders/00000.parquet", f"{root}/orders/00001.parquet"]
    assert not any(
        posixpath.basename(path) in {"_metadata", "_common_metadata"} for path in files
    )
    assert f"{root}/orders.parquet/" not in "\n".join(files)


@pytest.mark.parametrize(
    "write_request",
    [
        ParquetWriteRequest(path="once.parquet", mode="create", write_workers=2),
        ParquetWriteRequest(
            path="once-advanced",
            mode="create",
            filename_template="<increment>.parquet",
            write_workers=2,
        ),
        ParquetWriteRequest(
            path="once-row-cap",
            mode="create",
            filename_template="<increment>.parquet",
            row_cap=1,
            write_workers=2,
        ),
        ParquetWriteRequest(
            path="once-partitioned",
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["group"],
            write_workers=2,
        ),
    ],
)
def test_shared_upstream_dependency_executes_exactly_once(write_request):
    fs = _memory_fs()
    calls = [0]
    meta = pd.DataFrame(
        {
            "id": pd.Series(dtype="int64"),
            "group": pd.Series(dtype="string"),
        }
    )

    @dask.delayed
    def shared_dependency() -> int:
        calls[0] += 1
        return 100

    @dask.delayed
    def make_partition(index: int, shared_value: int) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "id": [shared_value + index],
                "group": pd.Series([f"g-{index % 2}"], dtype="string"),
            }
        )

    shared = shared_dependency()
    ddf = dd.from_delayed(
        [make_partition(index, shared) for index in range(4)],
        meta=meta,
    )
    write_dataframe(
        ddf,
        _memory_ctx(fs, write_request.path),
        write_request,
    )

    assert calls == [1]


@pytest.mark.parametrize("layout", [ParquetLayout.SIMPLE, ParquetLayout.ADVANCED])
def test_writer_activates_dataframe_operation_callbacks_once(layout):
    fs = _memory_fs()
    events = {"start": 0, "end": 0, "error": 0, "partitions": []}
    lock = threading.Lock()

    def on_start(_meta, operation_id):
        assert operation_id == "save_parquet_test"
        with lock:
            events["start"] += 1

    def on_end(_meta, operation_id):
        assert operation_id == "save_parquet_test"
        with lock:
            events["end"] += 1

    def on_error(_meta, operation_id, _exc):
        assert operation_id == "save_parquet_test"
        with lock:
            events["error"] += 1

    def on_partition(_pdf, operation_id, partition_info=None):
        assert operation_id == "save_parquet_test"
        with lock:
            events["partitions"].append(partition_info["number"])

    ddf = dd.from_pandas(
        pd.DataFrame({"value": [1, 2, 3, 4]}),
        npartitions=2,
    ).add_callbacks(
        on_start=on_start,
        on_end=on_end,
        on_error=on_error,
        on_partition=on_partition,
        operation_id="save_parquet_test",
    )
    path = "callbacks.parquet" if layout is ParquetLayout.SIMPLE else "callbacks"
    request = ParquetWriteRequest(
        path=path,
        mode="create",
        filename_template=None if layout is ParquetLayout.SIMPLE else "<increment>.parquet",
        write_workers=2,
    )

    write_dataframe(ddf, _memory_ctx(fs, path), request)

    assert events["start"] == 1
    assert events["end"] == 1
    assert events["error"] == 0
    assert sorted(events["partitions"]) == [0, 1]
    assert len(events["partitions"]) == len(set(events["partitions"]))


@pytest.mark.parametrize("layout", [ParquetLayout.SIMPLE, ParquetLayout.ADVANCED])
def test_writer_propagates_upstream_error_and_emits_error_lifecycle(layout):
    fs = _memory_fs()
    events = {"start": 0, "end": 0, "error": 0, "partitions": []}

    def fail_on_second_partition(pdf, partition_info=None):
        if partition_info["number"] == 1:
            raise RuntimeError("boom")
        return pdf

    base = dd.from_pandas(pd.DataFrame({"value": [1, 2, 3, 4]}), npartitions=2)
    failed = base.map_partitions(fail_on_second_partition, meta=base._meta)
    ddf = failed.add_callbacks(
        on_start=lambda *_args, **_kwargs: events.__setitem__("start", events["start"] + 1),
        on_end=lambda *_args, **_kwargs: events.__setitem__("end", events["end"] + 1),
        on_error=lambda *_args, **_kwargs: events.__setitem__("error", events["error"] + 1),
        on_partition=lambda _pdf, _op, partition_info=None, **_kwargs: events["partitions"].append(
            partition_info["number"]
        ),
        operation_id="save_parquet_failure_test",
    )
    path = "failed.parquet" if layout is ParquetLayout.SIMPLE else "failed"
    request = ParquetWriteRequest(
        path=path,
        mode="create",
        filename_template=None if layout is ParquetLayout.SIMPLE else "<increment>.parquet",
        write_workers=2,
    )

    with pytest.raises(RuntimeError, match="boom"):
        write_dataframe(ddf, _memory_ctx(fs, path), request)

    assert events["start"] == 1
    assert events["error"] == 1
    assert events["end"] == 0
    assert len(events["partitions"]) == len(set(events["partitions"]))
    assert _files(fs, f"/bucket/{path}") == []


def test_writer_does_not_duplicate_callbacks_inside_existing_public_callback_context():
    fs = _memory_fs()
    events = {"start": 0, "end": 0, "partitions": []}
    ddf = dd.from_pandas(pd.DataFrame({"value": [1, 2, 3, 4]}), npartitions=2).add_callbacks(
        on_start=lambda *_args, **_kwargs: events.__setitem__("start", events["start"] + 1),
        on_end=lambda *_args, **_kwargs: events.__setitem__("end", events["end"] + 1),
        on_partition=lambda _pdf, _op, partition_info=None, **_kwargs: events["partitions"].append(
            partition_info["number"]
        ),
        operation_id="save_parquet_nested_test",
    )

    with PublicOperationCallbacks(_collect_public_operation_callbacks_specs(ddf)):
        write_dataframe(
            ddf,
            _memory_ctx(fs, "nested.parquet"),
            ParquetWriteRequest(path="nested.parquet", mode="create"),
        )

    assert events["start"] == 1
    assert events["end"] == 1
    assert sorted(events["partitions"]) == [0, 1]


def test_writer_preserves_df_output_callback_metadata_and_cache_lifecycle():
    fs = _memory_fs()
    upstream_calls = [0]
    lifecycle = {"started": 0, "finished": 0, "progress": 0}

    class RecordingCacheWriter:
        def __init__(self) -> None:
            self.partitions: list[int] = []
            self.finish_calls = 0
            self.abort_calls = 0

        def submit_partition(self, _partition, *, part_no: int) -> None:
            self.partitions.append(part_no)

        def finish(self) -> bool:
            self.finish_calls += 1
            return True

        def abort(self) -> None:
            self.abort_calls += 1

    @dask.delayed
    def shared_dependency() -> int:
        upstream_calls[0] += 1
        return 10

    @dask.delayed
    def make_partition(index: int, shared: int) -> pd.DataFrame:
        return pd.DataFrame({"value": [shared + index]})

    shared = shared_dependency()
    ddf = dd.from_delayed(
        [make_partition(index, shared) for index in range(3)],
        meta=pd.DataFrame({"value": pd.Series(dtype="int64")}),
    )
    cache_writer = RecordingCacheWriter()
    coordinator = _NodeCallbacksCoordinator(
        on_started=lambda: lifecycle.__setitem__("started", lifecycle["started"] + 1),
        on_finished=lambda: lifecycle.__setitem__("finished", lifecycle["finished"] + 1),
    )
    partition_context = DDFPartitionCallbackContext(
        writer=cache_writer,
        progress_step=lambda: lifecycle.__setitem__("progress", lifecycle["progress"] + 1),
        progress_lock=threading.Lock(),
    )
    operation_id = "task:node:output"
    ddf = ddf.add_callbacks(
        on_start=_on_operation_start,
        on_end=_on_operation_end,
        on_partition=_on_operation_partition,
        on_error=_on_operation_error,
        metadata={
            "callback_coordinator": coordinator,
            "partition_context": partition_context,
        },
        metadata_token=operation_id,
        operation_id=operation_id,
        operation_type="node_df_output",
        copy_meta_mode="none",
        copy_partition_mode="none",
        partition_dispatch_mode="sync",
    )

    write_dataframe(
        ddf,
        _memory_ctx(fs, "df-output.parquet"),
        ParquetWriteRequest(path="df-output.parquet", mode="create"),
    )

    assert lifecycle == {"started": 1, "finished": 1, "progress": 3}
    assert sorted(cache_writer.partitions) == [0, 1, 2]
    assert len(cache_writer.partitions) == len(set(cache_writer.partitions))
    assert cache_writer.finish_calls == 1
    assert cache_writer.abort_calls == 0
    assert upstream_calls == [1]


def test_simple_preserves_source_partition_order_in_rows_and_row_groups():
    fs = _memory_fs()
    meta = pd.DataFrame({"id": pd.Series(dtype="int64")})
    ddf = dd.from_delayed(
        [
            dask.delayed(pd.DataFrame)({"id": list(range(start, start + 10))})
            for start in (0, 10, 20)
        ],
        meta=meta,
    )

    write_dataframe(
        ddf,
        _memory_ctx(fs, "ordered.parquet"),
        ParquetWriteRequest(path="ordered.parquet", mode="create"),
    )

    with fs.open("/bucket/ordered.parquet", "rb") as handle:
        parquet_file = pq.ParquetFile(handle)
        assert parquet_file.num_row_groups == 3
        assert [
                   parquet_file.read_row_group(index).column("id").to_pylist()
                   for index in range(parquet_file.num_row_groups)
               ] == [list(range(0, 10)), list(range(10, 20)), list(range(20, 30))]
        assert parquet_file.read().column("id").to_pylist() == list(range(30))


def test_simple_multiple_dask_partitions_create_one_physical_file():
    fs = _memory_fs()
    ddf = dd.from_pandas(pd.DataFrame({"id": range(20)}), npartitions=5)

    result = write_dataframe(
        ddf,
        _memory_ctx(fs, "reports/orders.parquet"),
        ParquetWriteRequest(path="reports/orders.parquet", mode="create"),
    )

    assert result.layout is ParquetLayout.SIMPLE
    assert result.files_written == 1
    assert _files(fs) == ["/bucket/reports/orders.parquet"]
    assert pd.read_parquet(fs.open("/bucket/reports/orders.parquet", "rb"))["id"].tolist() == list(
        range(20)
    )


def test_simple_write_index_compression_and_type_override():
    fs = _memory_fs()
    pdf = pd.DataFrame({"id": [1, 2, 3]}).set_index(pd.Index([10, 11, 12], name="row_id"))
    ddf = dd.from_pandas(pdf, npartitions=2)

    write_dataframe(
        ddf,
        _memory_ctx(fs, "orders.parquet"),
        ParquetWriteRequest(
            path="orders.parquet",
            mode="create",
            write_index=True,
            compression="gzip",
            parquet_types={"id": "int64"},
        ),
    )

    with fs.open("/bucket/orders.parquet", "rb") as handle:
        parquet_file = pq.ParquetFile(handle)
        assert parquet_file.metadata.row_group(0).column(0).compression == "GZIP"
        assert "row_id" in parquet_file.schema_arrow.names
        assert parquet_file.schema_arrow.field("id").type == pa.int64()


def test_simple_create_existing_file_errors_and_overwrite_replaces_only_target():
    fs = _memory_fs()
    fs.makedirs("/bucket/reports", exist_ok=True)
    fs.pipe("/bucket/reports/orders.parquet", b"old")
    fs.pipe("/bucket/reports/neighbor.txt", b"keep")
    ddf = dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1)
    ctx = _memory_ctx(fs, "reports/orders.parquet")

    with pytest.raises(FileExistsError, match="already exists"):
        write_dataframe(ddf, ctx, ParquetWriteRequest(path="reports/orders.parquet", mode="create"))

    write_dataframe(ddf, ctx, ParquetWriteRequest(path="reports/orders.parquet", mode="overwrite"))
    assert fs.cat("/bucket/reports/neighbor.txt") == b"keep"
    assert pd.read_parquet(fs.open("/bucket/reports/orders.parquet", "rb"))["id"].tolist() == [1]


def test_simple_empty_dataframe_creates_valid_file():
    fs = _memory_fs()
    ddf = dd.from_pandas(pd.DataFrame({"id": pd.Series(dtype="int64")}), npartitions=1)

    result = write_dataframe(
        ddf,
        _memory_ctx(fs, "empty.parquet"),
        ParquetWriteRequest(path="empty.parquet", mode="create"),
    )

    assert result.rows_written == 0
    assert pd.read_parquet(fs.open("/bucket/empty.parquet", "rb")).empty


def test_advanced_row_cap_increment_and_no_metadata_sidecars():
    fs = _memory_fs()
    ddf = dd.from_pandas(pd.DataFrame({"id": range(7)}), npartitions=2)

    result = write_dataframe(
        ddf,
        _memory_ctx(fs, "orders"),
        ParquetWriteRequest(
            path="orders",
            mode="create",
            row_cap=2,
            filename_template="data_<increment>",
        ),
    )

    files = _files(fs, "/bucket/orders")
    assert result.layout is ParquetLayout.ADVANCED
    assert files == [
        "/bucket/orders/data_00000.parquet",
        "/bucket/orders/data_00001.parquet",
        "/bucket/orders/data_00002.parquet",
        "/bucket/orders/data_00003.parquet",
    ]
    assert all(pq.read_table(fs.open(path, "rb")).num_rows <= 2 for path in files)
    assert not any(posixpath.basename(path) in {"_metadata", "_common_metadata"} for path in files)


def test_advanced_partition_on_uses_hive_directories_and_global_increment():
    fs = _memory_fs()
    pdf = pd.DataFrame({"id": [1, 2, 3], "country": ["RU", "US", "DE"]})
    ddf = dd.from_pandas(pdf, npartitions=1)

    write_dataframe(
        ddf,
        _memory_ctx(fs, "orders"),
        ParquetWriteRequest(
            path="orders",
            mode="create",
            partition_on=["country"],
            filename_template="<increment>.parquet",
        ),
    )

    files = _files(fs, "/bucket/orders")
    basenames = sorted(posixpath.basename(path) for path in files)
    assert basenames == ["00000.parquet", "00001.parquet", "00002.parquet"]
    assert {posixpath.basename(posixpath.dirname(path)) for path in files} == {
        "country=RU",
        "country=US",
        "country=DE",
    }


def test_uuid_is_unique_canonical_uuid4_per_physical_file():
    fs = _memory_fs()
    ddf = dd.from_pandas(pd.DataFrame({"id": range(5)}), npartitions=5)

    write_dataframe(
        ddf,
        _memory_ctx(fs, "orders"),
        ParquetWriteRequest(
            path="orders", mode="create", filename_template="prefix_<uuid>.parquet"
        ),
    )

    names = [posixpath.basename(path) for path in _files(fs, "/bucket/orders")]
    parsed = [uuid.UUID(name.removeprefix("prefix_").removesuffix(".parquet")) for name in names]
    assert len(set(parsed)) == 5
    assert all(value.version == 4 for value in parsed)


def test_increment_append_uses_max_existing_plus_one_with_hole():
    fs = _memory_fs()
    base = pd.DataFrame({"id": [1]})
    ddf = dd.from_pandas(base, npartitions=1)
    ctx = _memory_ctx(fs, "orders")
    write_dataframe(
        ddf,
        ctx,
        ParquetWriteRequest(path="orders", mode="create", filename_template="<increment>.parquet"),
    )
    for name in ("00002.parquet", "00003.parquet"):
        with fs.open(f"/bucket/orders/{name}", "wb") as handle:
            pq.write_table(pa.Table.from_pandas(base, preserve_index=False), handle)

    result = write_dataframe(
        ddf,
        ctx,
        ParquetWriteRequest(path="orders", mode="append", filename_template="<increment>.parquet"),
    )

    assert posixpath.basename(result.paths[0]) == "00004.parquet"


def test_increment_matcher_ignores_foreign_parquet_files():
    template = FilenameTemplate("prefix.<increment>_<uuid>.raw.parquet")

    assert (
            template.extract_increment("prefix.00042_550e8400-e29b-41d4-a716-446655440000.raw.parquet")
            == 42
    )
    assert template.extract_increment("foreign.99999.parquet") is None


@pytest.mark.parametrize(
    "template", ["../evil.parquet", "dir/file.parquet", "dir\\file.parquet", "\x00.parquet"]
)
def test_filename_template_rejects_path_content(template: str):
    with pytest.raises(ValueError):
        FilenameTemplate(template)


def test_partition_index_rejected_when_partition_can_split():
    fs = _memory_fs()
    ddf = dd.from_pandas(pd.DataFrame({"id": [1, 2], "country": ["RU", "US"]}), npartitions=1)

    with pytest.raises(ValueError, match="multiple output files"):
        write_dataframe(
            ddf,
            _memory_ctx(fs, "orders"),
            ParquetWriteRequest(
                path="orders",
                mode="create",
                partition_on=["country"],
                filename_template="<partition_index>.parquet",
            ),
        )


def test_append_unsafe_template_rejected_before_write():
    fs = _memory_fs()
    ddf = dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1)

    with pytest.raises(ValueError, match="unsafe for append"):
        write_dataframe(
            ddf,
            _memory_ctx(fs, "orders"),
            ParquetWriteRequest(path="orders", mode="append", filename_template="fixed.parquet"),
        )


def test_advanced_rejects_parquet_suffix_path():
    fs = _memory_fs()
    ddf = dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1)

    with pytest.raises(ValueError, match="dataset directory"):
        write_dataframe(
            ddf,
            _memory_ctx(fs, "orders.parquet"),
            ParquetWriteRequest(
                path="orders.parquet",
                mode="create",
                filename_template="<increment>.parquet",
            ),
        )


def test_overwrite_validates_schema_before_removing_existing_dataset():
    fs = _memory_fs()
    fs.pipe("/bucket/orders/keep.txt", b"keep")
    ddf = dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1)

    with pytest.raises(ValueError, match="do not exist"):
        write_dataframe(
            ddf,
            _memory_ctx(fs, "orders"),
            ParquetWriteRequest(
                path="orders",
                mode="overwrite",
                filename_template="<increment>.parquet",
                parquet_types={"missing": "int64"},
            ),
        )

    assert fs.cat("/bucket/orders/keep.txt") == b"keep"


def test_advanced_create_rejects_non_empty_target_and_overwrite_clears_only_target():
    fs = _memory_fs()
    fs.pipe("/bucket/orders/foreign.txt", b"x")
    fs.pipe("/bucket/neighbor.txt", b"keep")
    ddf = dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1)
    ctx = _memory_ctx(fs, "orders")
    request = ParquetWriteRequest(
        path="orders", mode="create", filename_template="<increment>.parquet"
    )

    with pytest.raises(FileExistsError, match="not empty"):
        write_dataframe(ddf, ctx, request)

    write_dataframe(
        ddf,
        ctx,
        ParquetWriteRequest(
            path="orders", mode="overwrite", filename_template="<increment>.parquet"
        ),
    )
    assert fs.cat("/bucket/neighbor.txt") == b"keep"
    assert "/bucket/orders/foreign.txt" not in _files(fs)


@pytest.mark.parametrize(
    ("write_request", "expected_rows"),
    [
        (ParquetWriteRequest(path="simple.parquet", mode="create"), 8),
        (
                ParquetWriteRequest(
                    path="increment",
                    mode="create",
                    filename_template="<increment>.parquet",
                ),
                8,
        ),
        (
                ParquetWriteRequest(
                    path="uuid",
                    mode="create",
                    filename_template="<uuid>.parquet",
                ),
                8,
        ),
        (
                ParquetWriteRequest(
                    path="capped",
                    mode="create",
                    filename_template="<increment>.parquet",
                    row_cap=2,
                ),
                8,
        ),
    ],
)
def test_memory_round_trip_simple_and_advanced(write_request, expected_rows):
    fs = _memory_fs()
    pdf = pd.DataFrame(
        {"id": range(expected_rows), "value": [f"v{i}" for i in range(expected_rows)]}
    )
    ddf = dd.from_pandas(pdf, npartitions=4)
    target = f"memory://bucket/{write_request.path}"
    write_dataframe(ddf, _memory_ctx(fs, write_request.path), write_request)

    result = (
        dd.read_parquet(target, engine="pyarrow").compute().sort_values("id").reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(result, pdf, check_dtype=False)


def test_partitioned_memory_round_trip_restores_partition_column():
    fs = _memory_fs()
    pdf = pd.DataFrame({"id": [1, 2, 3, 4], "country": ["RU", "US", "RU", "DE"]})
    ddf = dd.from_pandas(pdf, npartitions=2)
    request = ParquetWriteRequest(
        path="partitioned",
        mode="create",
        filename_template="<increment>.parquet",
        partition_on=["country"],
    )

    write_dataframe(ddf, _memory_ctx(fs, request.path), request)
    result = (
        dd.read_parquet("memory://bucket/partitioned", engine="pyarrow")
        .compute()
        .sort_values("id")
        .reset_index(drop=True)
    )
    result["country"] = result["country"].astype(str)
    pd.testing.assert_frame_equal(result, pdf)


def test_append_memory_round_trip_keeps_existing_rows():
    fs = _memory_fs()
    ctx = _memory_ctx(fs, "append")
    request = ParquetWriteRequest(
        path="append",
        mode="create",
        filename_template="<increment>.parquet",
    )
    write_dataframe(dd.from_pandas(pd.DataFrame({"id": [1, 2]}), npartitions=1), ctx, request)
    write_dataframe(
        dd.from_pandas(pd.DataFrame({"id": [3, 4]}), npartitions=1),
        ctx,
        ParquetWriteRequest(
            path="append",
            mode="append",
            filename_template="<increment>.parquet",
        ),
    )

    result = dd.read_parquet("memory://bucket/append", engine="pyarrow").compute()
    assert sorted(result["id"].tolist()) == [1, 2, 3, 4]


def test_append_schema_mismatch_writes_nothing():
    fs = _memory_fs()
    ctx = _memory_ctx(fs, "orders")
    write_dataframe(
        dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1),
        ctx,
        ParquetWriteRequest(path="orders", mode="create", filename_template="<increment>.parquet"),
    )
    before = _files(fs)

    with pytest.raises(ValueError, match="schema does not match"):
        write_dataframe(
            dd.from_pandas(pd.DataFrame({"id": ["x"]}), npartitions=1),
            ctx,
            ParquetWriteRequest(
                path="orders", mode="append", filename_template="<increment>.parquet"
            ),
        )

    assert _files(fs) == before


def test_append_validates_every_existing_physical_file_before_write():
    fs = _memory_fs()
    ctx = _memory_ctx(fs, "orders")
    request = ParquetWriteRequest(
        path="orders", mode="create", filename_template="<increment>.parquet"
    )
    write_dataframe(dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1), ctx, request)
    with fs.open("/bucket/orders/00001.parquet", "wb") as handle:
        pq.write_table(
            pa.Table.from_pandas(pd.DataFrame({"id": ["broken"]}), preserve_index=False),
            handle,
        )
    before = _files(fs)

    with pytest.raises(ValueError, match="schema does not match"):
        write_dataframe(
            dd.from_pandas(pd.DataFrame({"id": [2]}), npartitions=1),
            ctx,
            ParquetWriteRequest(
                path="orders", mode="append", filename_template="<increment>.parquet"
            ),
        )

    assert _files(fs) == before


@pytest.mark.parametrize(
    ("value", "parquet_type", "expected_segment"),
    [
        ("001", "int64", "part=1"),
        ("true", "bool", "part=true"),
        ("12.30", "decimal128(10,2)", "part=12.30"),
        ("2026-08-25", "date32", "part=2026-08-25"),
        (
                "2026-08-25T12:34:56",
                "timestamp[us]",
                "part=2026-08-25%2012%3A34%3A56.000000",
        ),
    ],
)
def test_partition_values_are_cast_and_rendered_from_declared_arrow_type(
        value, parquet_type, expected_segment
):
    fs = _memory_fs()
    write_dataframe(
        dd.from_pandas(pd.DataFrame({"id": [1], "part": [value]}), npartitions=1),
        _memory_ctx(fs, "typed-partition"),
        ParquetWriteRequest(
            path="typed-partition",
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["part"],
            parquet_types={"part": parquet_type},
        ),
    )

    assert expected_segment in _files(fs, "/bucket/typed-partition")[0]


def test_invalid_partition_cast_and_reserved_null_literal_leave_no_artifacts():
    for name, values, parquet_types, error in [
        ("bad-cast", ["abc"], {"part": "int64"}, "Cannot write Hive partition value"),
        (
                "reserved",
                ["__HIVE_DEFAULT_PARTITION__", None],
                None,
                "reserved for NULL values",
        ),
    ]:
        fs = _memory_fs()
        with pytest.raises(ValueError, match=error):
            write_dataframe(
                dd.from_pandas(pd.DataFrame({"id": range(len(values)), "part": values}), npartitions=1),
                _memory_ctx(fs, name),
                ParquetWriteRequest(
                    path=name,
                    mode="create",
                    filename_template="<increment>.parquet",
                    partition_on=["part"],
                    parquet_types=parquet_types,
                ),
            )
        assert _files(fs, f"/bucket/{name}") == []


def test_partition_column_parquet_type_override_is_stored_in_logical_schema():
    fs = _memory_fs()
    ctx = _memory_ctx(fs, "partitioned")
    write_dataframe(
        dd.from_pandas(pd.DataFrame({"id": [1], "country": ["001"]}), npartitions=1),
        ctx,
        ParquetWriteRequest(
            path="partitioned",
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["country"],
            parquet_types={"country": "large_string"},
        ),
    )

    stored = read_file_dataset_schema(
        ParquetFilesystem(ctx),
        _files(fs, "/bucket/partitioned")[0],
    )
    assert stored.logical is not None
    assert stored.logical.field("country").type == pa.large_string()
    assert "country" not in stored.physical.names


def test_append_validates_logical_partition_schema_before_writing():
    fs = _memory_fs()
    ctx = _memory_ctx(fs, "partitioned-append")
    write_dataframe(
        dd.from_pandas(
            pd.DataFrame({"id": [1], "part": pd.Series(["001"], dtype="string")}),
            npartitions=1,
        ),
        ctx,
        ParquetWriteRequest(
            path="partitioned-append",
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["part"],
        ),
    )
    before = _files(fs, "/bucket/partitioned-append")

    with pytest.raises(ValueError, match="logical schema does not match"):
        write_dataframe(
            dd.from_pandas(pd.DataFrame({"id": [2], "part": [1]}), npartitions=1),
            ctx,
            ParquetWriteRequest(
                path="partitioned-append",
                mode="append",
                filename_template="<increment>.parquet",
                partition_on=["part"],
            ),
        )

    assert _files(fs, "/bucket/partitioned-append") == before


@pytest.mark.parametrize("template", ["", "   ", "\t"])
def test_explicit_empty_filename_template_is_invalid(template: str):
    with pytest.raises(ValueError, match="cannot be empty"):
        FilenameTemplate(template)


def test_none_filename_template_uses_increment_default():
    assert FilenameTemplate(None).template == "<increment>.parquet"


@pytest.mark.parametrize(
    ("index_name", "column_name"),
    [
        ("row_id", "value"),
        (None, "value"),
        (None, "index"),
        (None, "level_0"),
        (None, "__index_level_0__"),
    ],
)
def test_write_index_preserves_index_and_reserved_user_columns(index_name, column_name):
    fs = _memory_fs()
    pdf = pd.DataFrame({column_name: [10, 20]}, index=pd.Index([5, 6], name=index_name))
    ddf = dd.from_pandas(pdf, npartitions=2)
    write_dataframe(
        ddf,
        _memory_ctx(fs, "indexed.parquet"),
        ParquetWriteRequest(path="indexed.parquet", mode="create", write_index=True),
    )

    result = pd.read_parquet(fs.open("/bucket/indexed.parquet", "rb"))
    assert result[column_name].tolist() == [10, 20]
    assert result.index.tolist() == [5, 6]
    assert result.index.name == index_name


def test_simple_self_overwrite_is_rejected_without_touching_source(tmp_path):
    path = tmp_path / "input.parquet"
    original = pd.DataFrame({"id": [1, 2, 3], "value": ["a", "b", "c"]})
    original.to_parquet(path, index=False)
    original_bytes = path.read_bytes()
    source = dd.read_parquet(path, engine="pyarrow")
    ctx = FsCtx(
        fs=fsspec.filesystem("file"),
        protocol="file",
        path=str(path),
        storage_options={},
    )

    with pytest.raises(ValueError, match="Read and write paths must not overlap"):
        write_dataframe(
            source,
            ctx,
            ParquetWriteRequest(path="input.parquet", mode="overwrite"),
        )

    assert path.read_bytes() == original_bytes
    pd.testing.assert_frame_equal(pd.read_parquet(path), original)


def test_advanced_self_overwrite_is_rejected_without_touching_dataset(tmp_path):
    path = tmp_path / "dataset"
    path.mkdir()
    pd.DataFrame({"id": [1, 2]}).to_parquet(path / "00000.parquet", index=False)
    pd.DataFrame({"id": [3, 4]}).to_parquet(path / "00001.parquet", index=False)
    before = {file.name: file.read_bytes() for file in path.iterdir()}
    source = dd.read_parquet(path, engine="pyarrow")
    ctx = FsCtx(
        fs=fsspec.filesystem("file"),
        protocol="file",
        path=str(path),
        storage_options={},
    )

    with pytest.raises(ValueError, match="Read and write paths must not overlap"):
        write_dataframe(
            source,
            ctx,
            ParquetWriteRequest(
                path="dataset",
                mode="overwrite",
                filename_template="<increment>.parquet",
            ),
        )

    assert {file.name: file.read_bytes() for file in path.iterdir()} == before
    assert sorted(dd.read_parquet(path).compute()["id"].tolist()) == [1, 2, 3, 4]


def test_advanced_overwrite_rejects_source_ancestor_of_target(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    pd.DataFrame({"id": [1]}).to_parquet(source_root / "part.parquet", index=False)
    source = dd.read_parquet(source_root, engine="pyarrow")
    target = source_root / "nested-target"
    ctx = FsCtx(
        fs=fsspec.filesystem("file"),
        protocol="file",
        path=str(target),
        storage_options={},
    )

    with pytest.raises(ValueError, match="Read and write paths must not overlap"):
        write_dataframe(
            source,
            ctx,
            ParquetWriteRequest(
                path="source/nested-target",
                mode="overwrite",
                filename_template="<increment>.parquet",
            ),
        )

    assert not target.exists()
    assert (source_root / "part.parquet").is_file()


def test_non_overlapping_overwrite_still_works(tmp_path):
    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    source_root.mkdir()
    target_root.mkdir()
    pd.DataFrame({"id": [1, 2]}).to_parquet(source_root / "part.parquet", index=False)
    pd.DataFrame({"id": [999]}).to_parquet(target_root / "old.parquet", index=False)
    source = dd.read_parquet(source_root, engine="pyarrow")
    ctx = FsCtx(
        fs=fsspec.filesystem("file"),
        protocol="file",
        path=str(target_root),
        storage_options={},
    )

    write_dataframe(
        source,
        ctx,
        ParquetWriteRequest(
            path="target",
            mode="overwrite",
            filename_template="<increment>.parquet",
        ),
    )

    assert sorted(dd.read_parquet(target_root).compute()["id"].tolist()) == [1, 2]
    assert not (target_root / "old.parquet").exists()


@pytest.mark.parametrize(
    "partition_on",
    [
        ["../escape"],
        ["a/b"],
        ["a\\b"],
        ["a=b"],
        ["g", "g"],
        [""],
    ],
)
def test_partition_columns_reject_unsafe_names_before_overwrite(partition_on):
    fs = _memory_fs()
    fs.pipe("/bucket/dataset/keep.parquet", b"keep-byte-for-byte")
    column = partition_on[0]
    columns = {"id": [1]}
    if column:
        columns[column] = ["x"]
    ddf = dd.from_pandas(pd.DataFrame(columns), npartitions=1)

    with pytest.raises(ValueError):
        write_dataframe(
            ddf,
            _memory_ctx(fs, "dataset"),
            ParquetWriteRequest(
                path="dataset",
                mode="overwrite",
                filename_template="<increment>.parquet",
                partition_on=partition_on,
            ),
        )

    assert fs.cat("/bucket/dataset/keep.parquet") == b"keep-byte-for-byte"
    assert _files(fs) == ["/bucket/dataset/keep.parquet"]


@pytest.mark.parametrize("column", ["country", "event_date", "customer_id"])
def test_partition_columns_accept_safe_hive_names(column):
    fs = _memory_fs()
    ddf = dd.from_pandas(pd.DataFrame({"id": [1], column: ["x"]}), npartitions=1)

    write_dataframe(
        ddf,
        _memory_ctx(fs, "dataset"),
        ParquetWriteRequest(
            path="dataset",
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=[column],
        ),
    )

    assert _files(fs) == [f"/bucket/dataset/{column}=x/00000.parquet"]


def test_advanced_create_rejects_nested_empty_directory(tmp_path):
    root = tmp_path / "dataset"
    nested = root / "leftover"
    nested.mkdir(parents=True)
    ctx = FsCtx(
        fs=fsspec.filesystem("file"),
        protocol="file",
        path=str(root),
        storage_options={},
    )

    with pytest.raises(FileExistsError, match="not empty"):
        write_dataframe(
            dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1),
            ctx,
            ParquetWriteRequest(
                path="dataset",
                mode="create",
                filename_template="<increment>.parquet",
            ),
        )

    assert nested.is_dir()
    assert list(root.rglob("*.parquet")) == []


def test_advanced_high_cardinality_partitioning_streams_many_physical_files():
    fs = _memory_fs()
    rows = 300
    pdf = pd.DataFrame({"id": range(rows), "group": [f"g-{i}" for i in range(rows)]})
    result = write_dataframe(
        dd.from_pandas(pdf, npartitions=4),
        _memory_ctx(fs, "many-groups"),
        ParquetWriteRequest(
            path="many-groups",
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["group"],
            write_workers=2,
        ),
    )

    assert result.files_written == rows
    assert result.rows_written == rows
