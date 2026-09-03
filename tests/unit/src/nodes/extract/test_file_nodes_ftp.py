from io import BytesIO
from pathlib import Path

import dask.dataframe as dd
import fsspec
import pandas as pd
import pytest

from core.parquet.write import ParquetWriteRequest, write_dataframe
from core.parquet.write.dask import find_source_paths
from core.types import FsCtx

from src.nodes.extract.load_csv import LoadCSV
from src.nodes.extract.load_excel import LoadExcel
from src.nodes.extract.load_json import LoadJSON
from src.nodes.extract.load_parquet import LoadParquet


class _ListingFTPFS:
    def __init__(
        self,
        *,
        exists: bool = True,
        glob_result: list[str] | None = None,
        info_type: str = "file",
        find_result: list[str] | None = None,
        files: dict[str, bytes] | None = None,
    ):
        self._exists = exists
        self._glob_result = list(glob_result or [])
        self._info_type = info_type
        self._find_result = list(find_result or [])
        self._files = dict(files or {})
        self.open_calls: list[tuple[str, str]] = []

    @staticmethod
    def _strip_protocol(path: str) -> str:
        if "://" not in path:
            return path
        remainder = path.split("://", 1)[1]
        slash_index = remainder.find("/")
        return remainder[slash_index:] if slash_index >= 0 else "/"

    def exists(self, _path: str) -> bool:
        return self._exists

    def info(self, _path: str) -> dict[str, str]:
        if not self._exists:
            raise FileNotFoundError(_path)
        return {"type": self._info_type}

    def glob(self, _path: str) -> list[str]:
        return list(self._glob_result)

    def find(self, _path: str, **_kwargs) -> list[str]:
        return list(self._find_result)

    def open(self, path: str, mode: str):
        self.open_calls.append((path, mode))
        return BytesIO(self._files[path])


class _DownloadFTPFS:
    def __init__(self, files: dict[str, bytes]):
        self.files = files
        self.get_file_calls: list[tuple[str, str]] = []

    _strip_protocol = staticmethod(_ListingFTPFS._strip_protocol)

    def get_file(self, remote_path: str, local_path: str) -> None:
        self.get_file_calls.append((remote_path, local_path))
        Path(local_path).write_bytes(self.files[remote_path])


def _make_context(path: str, *, fs: _ListingFTPFS | None = None) -> FsCtx:
    return FsCtx(
        fs=fs or _ListingFTPFS(),
        protocol="ftp",
        path=path,
        storage_options={
            "host": "ftp.local",
            "port": 2121,
            "username": "reader",
            "password": "secret",
            "timeout": 17,
        },
        host="ftp.local",
        port=2121,
        url_root="ftp://ftp.local:2121",
    )


def _patch_download_factory(monkeypatch, tmp_path, files: dict[str, bytes]):
    instances: list[_DownloadFTPFS] = []

    def factory(protocol: str, **_storage_options):
        assert protocol == "ftp"
        instance = _DownloadFTPFS(files)
        instances.append(instance)
        return instance

    monkeypatch.setattr("src.nodes.extract.ftp_file.fsspec.filesystem", factory)
    monkeypatch.setattr("src.nodes.extract.ftp_file.tempfile.tempdir", str(tmp_path))
    return instances


def test_load_csv_downloads_ftp_file_with_get_file(monkeypatch, tmp_path) -> None:
    path = "ftp://ftp.local:2121/reports/data.csv"
    ctx = _make_context(path)
    instances = _patch_download_factory(
        monkeypatch,
        tmp_path,
        {"/reports/data.csv": b"id,name\n1,Alice\n2,Bob\n"},
    )
    node = LoadCSV(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-csv-node",
        connection=object(),
        path="reports/data.csv",
    )
    monkeypatch.setattr(node, "_get_fs_context", lambda **_kwargs: ctx)

    result = node._read_csv().compute().reset_index(drop=True)

    assert result.to_dict(orient="records") == [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]
    assert instances
    assert all(instance.get_file_calls[0][0] == "/reports/data.csv" for instance in instances)
    assert list(tmp_path.iterdir()) == []


def test_load_excel_downloads_ftp_file_with_get_file(monkeypatch, tmp_path) -> None:
    path = "ftp://ftp.local:2121/reports/data.xlsx"
    buffer = BytesIO()
    pd.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]}).to_excel(buffer, index=False)
    instances = _patch_download_factory(
        monkeypatch,
        tmp_path,
        {"/reports/data.xlsx": buffer.getvalue()},
    )
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/data.xlsx",
    )

    result = node._read_excel_via_fs(_make_context(path), path, mode="full")

    assert result["name"].tolist() == ["Alice", "Bob"]
    assert len(instances) == 1
    assert instances[0].get_file_calls[0][0] == "/reports/data.xlsx"
    assert list(tmp_path.iterdir()) == []


def test_load_json_downloads_ftp_file_with_get_file(monkeypatch, tmp_path) -> None:
    path = "ftp://ftp.local:2121/reports/data.json"
    ctx = _make_context(path)
    instances = _patch_download_factory(
        monkeypatch,
        tmp_path,
        {"/reports/data.json": b'{"id": 1, "name": "Alice"}'},
    )
    node = LoadJSON(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-json-node",
        connection=object(),
        path="reports/data.json",
    )
    monkeypatch.setattr(node, "_get_fs_context", lambda **_kwargs: ctx)

    node.process()

    assert node.output == {"id": 1, "name": "Alice"}
    assert len(instances) == 1
    assert instances[0].get_file_calls[0][0] == "/reports/data.json"
    assert list(tmp_path.iterdir()) == []


def test_load_parquet_downloads_ftp_file_with_get_file(monkeypatch, tmp_path) -> None:
    path = "ftp://ftp.local:2121/reports/data.parquet"
    buffer = BytesIO()
    pd.DataFrame({"id": [1, 2], "name": ["Alice", "Bob"]}).to_parquet(
        buffer,
        index=False,
    )
    files = {"/reports/data.parquet": buffer.getvalue()}
    listing_fs = _ListingFTPFS(files=files)
    ctx = _make_context(path, fs=listing_fs)
    instances = _patch_download_factory(monkeypatch, tmp_path, files)
    node = LoadParquet(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-parquet-node",
        connection=object(),
        path="reports/data.parquet",
        usecols=None,
    )
    monkeypatch.setattr(node, "_get_fs_context", lambda **_kwargs: ctx)

    ddf = node._read_parquet()
    assert instances == []
    assert listing_fs.open_calls == [("/reports/data.parquet", "rb")]
    assert find_source_paths(ddf) == (path,)
    with pytest.raises(ValueError, match="Read and write paths must not overlap"):
        write_dataframe(
            ddf,
            ctx,
            ParquetWriteRequest(path="reports/data.parquet", mode="overwrite"),
        )
    assert instances == []

    result = ddf.compute().reset_index(drop=True)

    assert result.to_dict(orient="records") == [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]
    assert instances
    assert all(instance.get_file_calls[0][0] == "/reports/data.parquet" for instance in instances)
    assert list(tmp_path.iterdir()) == []


def test_save_new_partition_schema_round_trips_through_lazy_ftp_load(
    monkeypatch,
    tmp_path,
) -> None:
    source_fs = fsspec.filesystem("memory")
    source_fs.store.clear()
    source_ctx = FsCtx(
        fs=source_fs,
        protocol="memory",
        path="memory://source/orders",
        storage_options={},
    )
    expected = pd.DataFrame(
        {
            "id": range(6),
            "country": pd.Series(
                ["001", "00001", "true", "false", "1.5", None],
                dtype="string",
            ),
        }
    )
    write_dataframe(
        dd.from_pandas(expected, npartitions=2),
        source_ctx,
        ParquetWriteRequest(
            path="orders",
            mode="create",
            filename_template="<increment>.parquet",
            partition_on=["country"],
        ),
    )

    files = {
        path.replace("/source/orders", "/reports/orders", 1): source_fs.cat(path)
        for path in source_fs.find("/source/orders")
        if path.endswith(".parquet")
    }
    root = "ftp://ftp.local:2121/reports/orders"
    listing_fs = _ListingFTPFS(
        info_type="directory",
        find_result=list(files),
        files=files,
    )
    ctx = _make_context(root, fs=listing_fs)
    instances = _patch_download_factory(monkeypatch, tmp_path, files)
    node = LoadParquet(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-parquet-node",
        connection=object(),
        path="reports/orders",
        usecols=None,
    )
    monkeypatch.setattr(node, "_get_fs_context", lambda **_kwargs: ctx)

    ddf = node._read_parquet()
    assert instances == []

    actual = ddf.compute().sort_values("id").reset_index(drop=True)
    pd.testing.assert_series_equal(actual["country"], expected["country"], check_names=False)
    assert actual["id"].tolist() == expected["id"].tolist()


def test_load_parquet_reads_ftp_dataset_recursively_and_restores_hive_columns(
    monkeypatch,
    tmp_path,
) -> None:
    root = "ftp://ftp.local:2121/reports/orders"
    files: dict[str, bytes] = {}
    for remote_path, ids in {
        "/reports/orders/country=RU/00000.parquet": [1, 2],
        "/reports/orders/country=US/00001.parquet": [3],
    }.items():
        buffer = BytesIO()
        pd.DataFrame({"id": ids}).to_parquet(buffer, index=False)
        files[remote_path] = buffer.getvalue()

    listing_fs = _ListingFTPFS(
        info_type="directory",
        find_result=[*files, "/reports/orders/README.txt"],
        files=files,
    )
    ctx = _make_context(root, fs=listing_fs)
    instances = _patch_download_factory(monkeypatch, tmp_path, files)
    node = LoadParquet(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-parquet-node",
        connection=object(),
        path="reports/orders",
        usecols=None,
    )
    monkeypatch.setattr(node, "_get_fs_context", lambda **_kwargs: ctx)

    result = node._read_parquet().compute().sort_values("id").reset_index(drop=True)

    assert result.to_dict(orient="records") == [
        {"id": 1, "country": "RU"},
        {"id": 2, "country": "RU"},
        {"id": 3, "country": "US"},
    ]
    downloaded = [call[0] for instance in instances for call in instance.get_file_calls]
    assert sorted(downloaded) == sorted(files)
    assert list(tmp_path.iterdir()) == []
