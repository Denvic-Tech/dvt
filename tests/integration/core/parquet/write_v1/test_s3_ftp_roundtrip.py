from __future__ import annotations

import os
import posixpath
import uuid

import dask.dataframe as dd
import fsspec
import pandas as pd
import pyarrow.parquet as pq
import pytest

import core.parquet.write.writer as parquet_writer
from core.parquet.write import ParquetWriteRequest, write_dataframe
from core.parquet.write.dask import find_source_paths
from core.types import FsCtx

from src.nodes.extract.load_parquet import LoadParquet

pytestmark = pytest.mark.docker_required

_BUCKET = "dvt-save-parquet-write-v1-tests"


def _service_host() -> str:
    return os.getenv("DVT_TEST_SERVICE_HOST") or (
        "host.docker.internal"
        if os.getenv("TESTCONTAINERS_HOST_OVERRIDE")
        else "127.0.0.1"
    )


def _s3_fs():
    endpoint = os.getenv("MINIO_TEST_ENDPOINT", f"http://{_service_host()}:3900")
    options = {
        "key": os.getenv("MINIO_ROOT_USER", "minioadmin"),
        "secret": os.getenv("MINIO_ROOT_PASSWORD", "minioadmin"),
        "endpoint_url": endpoint,
        "client_kwargs": {"verify": False},
        "config_kwargs": {"s3": {"addressing_style": "path"}},
    }
    fs = fsspec.filesystem("s3", **options)
    if not fs.exists(_BUCKET):
        fs.mkdir(_BUCKET)
    return fs, options


def _s3_ctx(fs, options: dict, key: str) -> FsCtx:
    return FsCtx(
        fs=fs,
        protocol="s3",
        path=f"s3://{_BUCKET}/{key}",
        storage_options=options,
    )


def _ftp_fs():
    host = os.getenv("FTP_TEST_HOST", _service_host())
    port = int(os.getenv("FTP_TEST_PORT", "9021"))
    options = {
        "host": host,
        "port": port,
        "username": os.getenv("FTP_TEST_USER", "ftpuser"),
        "password": os.getenv("FTP_TEST_PASSWORD", "ftppassword"),
        "timeout": 30,
    }
    return fsspec.filesystem("ftp", **options), options


def _ftp_ctx(fs, options: dict, path: str) -> FsCtx:
    host = str(options["host"])
    port = int(options["port"])
    return FsCtx(
        fs=fs,
        protocol="ftp",
        path=f"ftp://{host}:{port}/{path.lstrip('/')}",
        storage_options=options,
        host=host,
        port=port,
        url_root=f"ftp://{host}:{port}",
    )


def _load(ctx: FsCtx, logical_path: str, monkeypatch) -> dd.DataFrame:
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
    return node._read_parquet()


def _assert_roundtrip(ddf: dd.DataFrame, expected: pd.DataFrame) -> None:
    actual = ddf.compute().sort_values("id").reset_index(drop=True)
    expected = expected.sort_values("id").reset_index(drop=True)
    if "country" in actual.columns:
        actual["country"] = actual["country"].astype(str)
    pd.testing.assert_frame_equal(actual, expected, check_dtype=False)


def test_write_v1_real_minio_s3_layout_modes_roundtrip_and_cleanup(monkeypatch) -> None:
    fs, options = _s3_fs()
    root = "write-v1-s3"
    if fs.exists(f"{_BUCKET}/{root}"):
        fs.rm(f"{_BUCKET}/{root}", recursive=True)
    pdf = pd.DataFrame(
        {
            "id": range(9),
            "country": ["RU", "US", "DE"] * 3,
        }
    )
    ddf = dd.from_pandas(pdf, npartitions=3)

    simple_key = f"{root}/orders.parquet"
    simple_ctx = _s3_ctx(fs, options, simple_key)
    write_dataframe(
        ddf,
        simple_ctx,
        ParquetWriteRequest(path=simple_key, mode="create"),
    )
    simple_object = f"{_BUCKET}/{simple_key}"
    assert fs.isfile(simple_object)
    assert not any(
        path.startswith(f"{simple_object}/")
        for path in fs.find(f"{_BUCKET}/{root}")
    )
    simple_load = _load(simple_ctx, simple_key, monkeypatch)
    before_simple = fs.cat(simple_object)
    with pytest.raises(ValueError, match="Read and write paths must not overlap"):
        write_dataframe(
            simple_load,
            simple_ctx,
            ParquetWriteRequest(path=simple_key, mode="overwrite"),
        )
    assert fs.cat(simple_object) == before_simple
    _assert_roundtrip(simple_load, pdf)

    increment_key = f"{root}/increment"
    increment_ctx = _s3_ctx(fs, options, increment_key)
    write_dataframe(
        ddf,
        increment_ctx,
        ParquetWriteRequest(
            path=increment_key,
            mode="create",
            filename_template="<increment>.parquet",
        ),
    )
    assert sorted(posixpath.basename(path) for path in fs.find(f"{_BUCKET}/{increment_key}")) == [
        "00000.parquet",
        "00001.parquet",
        "00002.parquet",
    ]

    uuid_key = f"{root}/uuid"
    uuid_ctx = _s3_ctx(fs, options, uuid_key)
    write_dataframe(
        ddf,
        uuid_ctx,
        ParquetWriteRequest(path=uuid_key, mode="create", filename_template="<uuid>.parquet"),
    )
    uuid_names = [posixpath.basename(path).removesuffix(".parquet") for path in fs.find(f"{_BUCKET}/{uuid_key}")]
    assert len(uuid_names) == 3
    assert all(uuid.UUID(name).version == 4 for name in uuid_names)

    capped_key = f"{root}/capped"
    capped_ctx = _s3_ctx(fs, options, capped_key)
    write_dataframe(
        ddf,
        capped_ctx,
        ParquetWriteRequest(
            path=capped_key,
            mode="create",
            filename_template="<increment>.parquet",
            row_cap=2,
        ),
    )
    capped_files = fs.find(f"{_BUCKET}/{capped_key}")
    assert len(capped_files) == 6
    assert all(pq.read_table(fs.open(path, "rb")).num_rows <= 2 for path in capped_files)

    partitioned_key = f"{root}/partitioned"
    partitioned_ctx = _s3_ctx(fs, options, partitioned_key)
    write_dataframe(
        ddf,
        partitioned_ctx,
        ParquetWriteRequest(
            path=partitioned_key,
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["country"],
        ),
    )
    _assert_roundtrip(_load(partitioned_ctx, partitioned_key, monkeypatch), pdf)

    category_key = f"{root}/category"
    category_ctx = _s3_ctx(fs, options, category_key)
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
            path=category_key,
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["category"],
        ),
    )
    category_actual = _load(category_ctx, category_key, monkeypatch).compute().sort_values("id")
    assert str(category_actual["category"].dtype) == "category"
    assert (
        category_actual["category"]
        .astype(object)
        .where(category_actual["category"].notna(), None)
        .tolist()
        == ["RU", "US", "RU", None]
    )

    append_key = f"{root}/append"
    append_ctx = _s3_ctx(fs, options, append_key)
    first = pd.DataFrame({"id": [1, 2]})
    write_dataframe(
        dd.from_pandas(first, npartitions=1),
        append_ctx,
        ParquetWriteRequest(
            path=append_key,
            mode="create",
            filename_template="<increment>.parquet",
        ),
    )
    fs.mv(
        f"{_BUCKET}/{append_key}/00000.parquet",
        f"{_BUCKET}/{append_key}/00003.parquet",
    )
    write_dataframe(
        dd.from_pandas(pd.DataFrame({"id": [3]}), npartitions=1),
        append_ctx,
        ParquetWriteRequest(
            path=append_key,
            mode="append",
            filename_template="<increment>.parquet",
        ),
    )
    assert fs.exists(f"{_BUCKET}/{append_key}/00004.parquet")

    overwrite_source = dd.from_pandas(pd.DataFrame({"id": [7]}), npartitions=1)
    write_dataframe(
        overwrite_source,
        append_ctx,
        ParquetWriteRequest(
            path=append_key,
            mode="overwrite",
            filename_template="<increment>.parquet",
        ),
    )
    assert sorted(posixpath.basename(path) for path in fs.find(f"{_BUCKET}/{append_key}")) == [
        "00000.parquet"
    ]

    objects = fs.find(f"{_BUCKET}/{root}")
    assert not any(path.endswith("/") for path in objects)
    assert not any(posixpath.basename(path) in {"_metadata", "_common_metadata"} for path in objects)

    bad_key = f"{root}/cleanup"
    bad_ctx = _s3_ctx(fs, options, bad_key)
    original_write_one = parquet_writer._write_one_file
    calls = 0

    def fail_after_transport_write(*args, **kwargs):
        nonlocal calls
        result = original_write_one(*args, **kwargs)
        calls += 1
        if calls == 2:
            raise RuntimeError("injected transport write failure")
        return result

    monkeypatch.setattr(parquet_writer, "_write_one_file", fail_after_transport_write)
    with pytest.raises(RuntimeError, match="injected transport write failure"):
        write_dataframe(
            dd.from_pandas(pd.DataFrame({"id": range(4)}), npartitions=2),
            bad_ctx,
            ParquetWriteRequest(
                path=bad_key,
                mode="create",
                filename_template="<increment>.parquet",
                write_workers=1,
            ),
        )
    assert fs.find(f"{_BUCKET}/{bad_key}") == []
    monkeypatch.setattr(parquet_writer, "_write_one_file", original_write_one)


def test_write_v1_real_ftp_layout_append_partition_load_and_lazy_graph(monkeypatch) -> None:
    fs, options = _ftp_fs()
    root = "home/ftpuser/write-v1-ftp"
    if fs.exists(root):
        fs.rm(root, recursive=True)
    pdf = pd.DataFrame(
        {
            "id": range(6),
            "country": ["RU", "US", "DE", "RU", "US", "DE"],
        }
    )
    ddf = dd.from_pandas(pdf, npartitions=2)

    simple_path = f"{root}/orders.parquet"
    simple_ctx = _ftp_ctx(fs, options, simple_path)
    write_dataframe(
        ddf,
        simple_ctx,
        ParquetWriteRequest(path=simple_path, mode="create"),
    )
    assert fs.isfile(simple_path)
    simple_load = _load(simple_ctx, simple_path, monkeypatch)
    assert find_source_paths(simple_load) == (simple_ctx.path,)
    before_simple = fs.cat(simple_path)
    with pytest.raises(ValueError, match="Read and write paths must not overlap"):
        write_dataframe(
            simple_load,
            simple_ctx,
            ParquetWriteRequest(path=simple_path, mode="overwrite"),
        )
    assert fs.cat(simple_path) == before_simple
    _assert_roundtrip(simple_load, pdf)

    increment_path = f"{root}/increment"
    increment_ctx = _ftp_ctx(fs, options, increment_path)
    write_dataframe(
        ddf,
        increment_ctx,
        ParquetWriteRequest(
            path=increment_path,
            mode="create",
            filename_template="<increment>.parquet",
        ),
    )
    assert sorted(posixpath.basename(path) for path in fs.find(increment_path)) == [
        "00000.parquet",
        "00001.parquet",
    ]

    uuid_path = f"{root}/uuid"
    uuid_ctx = _ftp_ctx(fs, options, uuid_path)
    write_dataframe(
        ddf,
        uuid_ctx,
        ParquetWriteRequest(path=uuid_path, mode="create", filename_template="<uuid>.parquet"),
    )
    assert all(
        uuid.UUID(posixpath.basename(path).removesuffix(".parquet")).version == 4
        for path in fs.find(uuid_path)
    )

    partitioned_path = f"{root}/partitioned"
    partitioned_ctx = _ftp_ctx(fs, options, partitioned_path)
    write_dataframe(
        ddf,
        partitioned_ctx,
        ParquetWriteRequest(
            path=partitioned_path,
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["country"],
            row_cap=1,
        ),
    )
    partitioned_load = _load(partitioned_ctx, partitioned_path, monkeypatch)
    assert len(find_source_paths(partitioned_load)) == 6
    _assert_roundtrip(partitioned_load, pdf)

    category_path = f"{root}/category"
    category_ctx = _ftp_ctx(fs, options, category_path)
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
            path=category_path,
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["category"],
        ),
    )
    category_actual = _load(category_ctx, category_path, monkeypatch).compute().sort_values("id")
    assert str(category_actual["category"].dtype) == "category"
    assert (
        category_actual["category"]
        .astype(object)
        .where(category_actual["category"].notna(), None)
        .tolist()
        == ["RU", "US", "RU", None]
    )
    assert not category_actual["category"].isna().iloc[:3].any()

    append_path = f"{root}/append"
    append_ctx = _ftp_ctx(fs, options, append_path)
    write_dataframe(
        dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1),
        append_ctx,
        ParquetWriteRequest(
            path=append_path,
            mode="create",
            filename_template="<increment>.parquet",
        ),
    )
    fs.mv(f"{append_path}/00000.parquet", f"{append_path}/00002.parquet")
    write_dataframe(
        dd.from_pandas(pd.DataFrame({"id": [2]}), npartitions=1),
        append_ctx,
        ParquetWriteRequest(
            path=append_path,
            mode="append",
            filename_template="<increment>.parquet",
        ),
    )
    assert fs.exists(f"{append_path}/00003.parquet")

    write_dataframe(
        dd.from_pandas(pd.DataFrame({"id": [9]}), npartitions=1),
        append_ctx,
        ParquetWriteRequest(
            path=append_path,
            mode="overwrite",
            filename_template="<increment>.parquet",
        ),
    )
    assert sorted(posixpath.basename(path) for path in fs.find(append_path)) == [
        "00000.parquet"
    ]

    nested_create_path = f"{root}/nested-create"
    fs.makedirs(f"{nested_create_path}/leftover", exist_ok=True)
    nested_create_ctx = _ftp_ctx(fs, options, nested_create_path)
    with pytest.raises(FileExistsError, match="not empty"):
        write_dataframe(
            dd.from_pandas(pd.DataFrame({"id": [1]}), npartitions=1),
            nested_create_ctx,
            ParquetWriteRequest(
                path=nested_create_path,
                mode="create",
                filename_template="<increment>.parquet",
            ),
        )
    assert fs.isdir(f"{nested_create_path}/leftover")
    assert not fs.find(nested_create_path)

    bad_path = f"{root}/cleanup"
    bad_ctx = _ftp_ctx(fs, options, bad_path)
    original_write_one = parquet_writer._write_one_file
    calls = 0

    def fail_after_transport_write(*args, **kwargs):
        nonlocal calls
        result = original_write_one(*args, **kwargs)
        calls += 1
        if calls == 2:
            raise RuntimeError("injected transport write failure")
        return result

    monkeypatch.setattr(parquet_writer, "_write_one_file", fail_after_transport_write)
    with pytest.raises(RuntimeError, match="injected transport write failure"):
        write_dataframe(
            dd.from_pandas(pd.DataFrame({"id": range(4)}), npartitions=2),
            bad_ctx,
            ParquetWriteRequest(
                path=bad_path,
                mode="create",
                filename_template="<increment>.parquet",
                write_workers=1,
            ),
        )
    assert fs.find(bad_path) == []
