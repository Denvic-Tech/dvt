from collections import Counter
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

import dask.dataframe as dd
import fsspec
import pandas as pd
import pytest

from core.types import Column, DataFrameMetadata, DataType, FsCtx

from src.node_dsl.runtime.integrations.file_connection.filesystem import FileConnectionRuntime
from src.nodes.extract.load_csv import LoadCSV
from src.nodes.extract.load_excel import LoadExcel
from src.nodes.extract.load_parquet import LoadParquet


class _FakeSMBFS:
    def __init__(self, *, glob_result=None, exists_result=True, file_bytes: bytes = b""):
        self._glob_result = list(glob_result or [])
        self._exists_result = exists_result
        self._file_bytes = file_bytes

    def _strip_protocol(self, path: str) -> str:
        if "://" not in path:
            return path
        remainder = path.split("://", 1)[1]
        slash_index = remainder.find("/")
        return remainder[slash_index:] if slash_index >= 0 else "/"

    def glob(self, path: str):
        return list(self._glob_result)

    def exists(self, path: str) -> bool:
        return self._exists_result

    def info(self, path: str) -> dict[str, str]:
        if not self._exists_result:
            raise FileNotFoundError(path)
        return {"type": "file"}

    @contextmanager
    def open(self, path: str, mode: str):
        file_obj = BytesIO(self._file_bytes if "r" in mode else b"")
        file_obj.path = path
        yield file_obj


class _FakeFTPFS:
    def __init__(self, *, fs_id: str, glob_result=None, exists_result=True):
        self.fs_id = fs_id
        self._glob_result = list(glob_result or [])
        self._exists_result = exists_result

    def _strip_protocol(self, path: str) -> str:
        if "://" not in path:
            return path
        remainder = path.split("://", 1)[1]
        slash_index = remainder.find("/")
        return remainder[slash_index:] if slash_index >= 0 else "/"

    def glob(self, path: str):
        return list(self._glob_result)

    def exists(self, path: str) -> bool:
        return self._exists_result

    def info(self, path: str) -> dict[str, str]:
        if not self._exists_result:
            raise FileNotFoundError(path)
        return {"type": "file"}

    def get_file(self, remote_path: str, local_path: str) -> None:
        Path(local_path).write_bytes(remote_path.encode("utf-8"))

    @contextmanager
    def open(self, path: str, mode: str, **_kwargs):
        file_obj = BytesIO()
        file_obj.path = path
        file_obj.fs_id = self.fs_id
        yield file_obj


class _FakeS3FS(_FakeSMBFS):
    def _strip_protocol(self, path: str) -> str:
        return path.split("://", 1)[-1].lstrip("/")


def _make_smb_context(path: str, *, fs=None) -> FsCtx:
    return FsCtx(
        fs=fs or _FakeSMBFS(),
        protocol="smb",
        path=path,
        storage_options={
            "host": "fileserver",
            "port": 445,
            "username": "reader",
            "password": "secret",
        },
        host="fileserver",
        port=445,
        url_root="smb://fileserver:445",
    )


def _make_s3_context(path: str, *, fs=None) -> FsCtx:
    return FsCtx(
        fs=fs or _FakeS3FS(),
        protocol="s3",
        path=path,
        storage_options={},
        url_root="s3://",
    )


def _make_ftp_context(path: str, *, fs=None) -> FsCtx:
    return FsCtx(
        fs=fs or _FakeFTPFS(fs_id="shared"),
        protocol="ftp",
        path=path,
        storage_options={
            "host": "ftp.local",
            "port": 2121,
            "username": "ftpuser",
            "password": "secret",
            "timeout": 11,
            "block_size": 1024 * 1024,
        },
        host="ftp.local",
        port=2121,
        url_root="ftp://ftp.local:2121",
    )


def test_load_csv_reads_from_smb_path(monkeypatch):
    captured = {}
    node = LoadCSV(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-csv-node",
        connection=object(),
        path="reports/data.csv",
    )

    monkeypatch.setattr(
        node,
        "_get_fs_context",
        lambda **_kwargs: _make_smb_context("smb://fileserver:445/shared/reports/data.csv"),
    )
    monkeypatch.setattr(
        dd,
        "read_csv",
        lambda path, dtype=None, **kwargs: (
            captured.update({"path": path, "dtype": dtype, "kwargs": kwargs}) or "csv-ddf"
        ),
    )

    result = node._read_csv()

    assert result == "csv-ddf"
    assert captured["path"] == "smb://fileserver:445/shared/reports/data.csv"
    assert captured["kwargs"]["storage_options"]["host"] == "fileserver"


def test_load_parquet_reads_from_smb_path(monkeypatch):
    captured = {}
    node = LoadParquet(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-parquet-node",
        connection=object(),
        path="reports/data.parquet",
    )

    parquet_buffer = BytesIO()
    pd.DataFrame({"id": [1]}).to_parquet(parquet_buffer, index=False)
    monkeypatch.setattr(
        node,
        "_get_fs_context",
        lambda **_kwargs: _make_smb_context(
            "smb://fileserver:445/shared/reports/data.parquet",
            fs=_FakeSMBFS(file_bytes=parquet_buffer.getvalue()),
        ),
    )
    monkeypatch.setattr(
        dd,
        "read_parquet",
        lambda path, **kwargs: captured.update({"path": path, "kwargs": kwargs}) or "parquet-ddf",
    )

    result = node._read_parquet()

    assert result == "parquet-ddf"
    assert captured["path"] == "smb://fileserver:445/shared/reports/data.parquet"
    assert captured["kwargs"]["storage_options"]["host"] == "fileserver"


def test_load_excel_list_files_rebuilds_full_smb_urls():
    ctx = _make_smb_context(
        "smb://fileserver:445/shared/reports/*.xlsx",
        fs=_FakeSMBFS(
            glob_result=["/shared/reports/a.xlsx", "/shared/reports/b.xlsx"],
            exists_result=False,
        ),
    )

    files = FileConnectionRuntime(ctx).list_files()

    assert files == [
        "smb://fileserver:445/shared/reports/a.xlsx",
        "smb://fileserver:445/shared/reports/b.xlsx",
    ]


def test_load_excel_list_files_preserves_s3_protocol_for_cyrillic_glob():
    matched_path = (
        "dvt/denvic_folder/Несколько Ексель/"
        "По проектам_2026-07-24_17-20-43 — копия (2).xlsx"
    )
    ctx = _make_s3_context(
        "s3://dvt/denvic_folder/Несколько Ексель/По проектам_*.xlsx",
        fs=_FakeS3FS(glob_result=[matched_path]),
    )

    files = FileConnectionRuntime(ctx).list_files()

    assert files == [f"s3://{matched_path}"]


@pytest.mark.asyncio
async def test_load_excel_process_metadata_builds_empty_ddf(monkeypatch):
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/file.xlsx",
    )

    async def fake_resolve_metadata():
        return {
            "output": DataFrameMetadata(
                columns=[
                    Column(name="id", dtype=DataType.INT, nullable=True, index=False),
                    Column(name="name", dtype=DataType.STRING, nullable=True, index=False),
                ]
            )
        }

    monkeypatch.setattr(node, "resolve_metadata", fake_resolve_metadata)

    await node.process_metadata()

    assert list(node.output.columns) == ["id", "name"]
    assert node.output.npartitions == 1


def test_load_excel_infer_metadata_reads_first_file_with_optimized_kwargs(monkeypatch):
    captured = {}
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/file.xlsx",
    )
    ctx = _make_smb_context("smb://fileserver:445/shared/reports/file.xlsx")

    monkeypatch.setattr(node, "_get_fs_context", lambda **_kwargs: ctx)

    def fake_read_excel(file_obj, **kwargs):
        captured["path"] = getattr(file_obj, "path", None)
        captured["kwargs"] = kwargs
        return pd.DataFrame(
            {"id": pd.Series([1], dtype="Int64"), "name": pd.Series(["x"], dtype="string")}
        )

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    metadata = node.infer_metadata()

    assert captured["path"] == ctx.path
    assert captured["kwargs"]["nrows"] == 32
    assert captured["kwargs"]["engine"] == "openpyxl"
    assert captured["kwargs"]["engine_kwargs"] == {"read_only": True, "data_only": True}
    assert captured["kwargs"]["decimal"] == "."
    assert "thousands" not in captured["kwargs"]
    assert metadata["output"].columns[0].name == "id"
    assert metadata["output"].columns[0].dtype == DataType.FLOAT
    assert metadata["output"].columns[1].name == "name"


def test_load_excel_process_preserves_fractional_values_after_integer_sample(
    monkeypatch,
    tmp_path,
):
    excel_path = tmp_path / "amounts.xlsx"
    pd.DataFrame({"amount": [100] * 32 + [39.01, 5214.06]}).to_excel(
        excel_path,
        index=False,
    )
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path=str(excel_path),
    )
    ctx = FsCtx(
        fs=fsspec.filesystem("file"),
        protocol="file",
        path=str(excel_path),
        storage_options={},
    )

    monkeypatch.setattr(node, "_get_fs_context", lambda **_kwargs: ctx)

    node.process()
    result = node.output.compute().reset_index(drop=True)

    assert str(result["amount"].dtype) == "Float64"
    assert result["amount"].tail(2).tolist() == [39.01, 5214.06]


@pytest.mark.parametrize(
    ("dtype_name", "expected_dtype", "values"),
    [
        ("Float64", "Float64", [100.0, 39.01]),
        ("string", "string", ["100", "39.01"]),
    ],
)
def test_load_excel_explicit_dtype_has_priority(
    monkeypatch,
    dtype_name,
    expected_dtype,
    values,
):
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/file.xlsx",
        dtypes={"amount": dtype_name},
    )
    ctx = _make_smb_context("smb://fileserver:445/shared/reports/file.xlsx")

    def fake_read_excel(_file_obj, **kwargs):
        assert kwargs["dtype"] == {"amount": dtype_name}
        return pd.DataFrame({"amount": pd.Series(values, dtype=expected_dtype)})

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    result = node._read_excel_via_fs(ctx, ctx.path, mode="full")

    assert str(result["amount"].dtype) == expected_dtype
    assert result["amount"].tolist() == values


def test_load_excel_reads_locale_formatted_text_numbers_as_float(
    monkeypatch,
    tmp_path,
):
    excel_path = tmp_path / "locale-numbers.xlsx"
    pd.DataFrame(
        {
            "row_id": [1, 2, 3, 4, 5, 6],
            "3 Брусок": ["4 604", "39,01", "5214.06", "#ССЫЛКА!", "#REF!", None],
        }
    ).to_excel(excel_path, index=False)
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path=str(excel_path),
        dtypes={"3 Брусок": "Float64"},
        thousands=" ",
        decimal=",",
    )
    ctx = FsCtx(
        fs=fsspec.filesystem("file"),
        protocol="file",
        path=str(excel_path),
        storage_options={},
    )

    monkeypatch.setattr(node, "_get_fs_context", lambda **_kwargs: ctx)

    metadata = node.infer_metadata()
    node.process()
    result = node.output.compute().reset_index(drop=True)

    column_metadata = next(
        column for column in metadata["output"].columns if column.name == "3 Брусок"
    )
    assert column_metadata.dtype == DataType.FLOAT
    assert str(result["3 Брусок"].dtype) == "Float64"
    assert result["3 Брусок"].iloc[:3].tolist() == [4604.0, 39.01, 5214.06]
    assert result["3 Брусок"].iloc[3:].isna().all()


def test_load_excel_explicit_float_still_rejects_unknown_text(tmp_path):
    excel_path = tmp_path / "invalid-number.xlsx"
    pd.DataFrame({"amount": ["10,5", "not-a-number"]}).to_excel(excel_path, index=False)
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path=str(excel_path),
        dtypes={"amount": "Float64"},
        decimal=",",
    )
    ctx = FsCtx(
        fs=fsspec.filesystem("file"),
        protocol="file",
        path=str(excel_path),
        storage_options={},
    )

    with pytest.raises(ValueError, match="Failed to read Excel with explicit dtypes"):
        node._read_excel_via_fs(ctx, ctx.path, mode="full")


def test_load_excel_explicit_string_preserves_locale_formatted_value(
    monkeypatch,
    tmp_path,
):
    excel_path = tmp_path / "locale-string.xlsx"
    pd.DataFrame({"code": ["1 234", "5 678"]}).to_excel(excel_path, index=False)
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path=str(excel_path),
        dtypes={"code": "string"},
        thousands=" ",
        decimal=",",
    )
    ctx = FsCtx(
        fs=fsspec.filesystem("file"),
        protocol="file",
        path=str(excel_path),
        storage_options={},
    )

    result = node._read_excel_via_fs(ctx, ctx.path, mode="full")

    assert str(result["code"].dtype) == "string"
    assert result["code"].tolist() == ["1 234", "5 678"]


def test_load_excel_explicit_integer_dtype_rejects_fractional_values(monkeypatch):
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/file.xlsx",
        dtypes={"amount": "Int64"},
    )
    ctx = _make_smb_context("smb://fileserver:445/shared/reports/file.xlsx")

    def fake_read_excel(_file_obj, **kwargs):
        assert kwargs["dtype"] == {"amount": "Int64"}
        raise TypeError("cannot safely cast non-equivalent float64 to int64")

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    with pytest.raises(ValueError, match="Failed to read Excel with explicit dtypes"):
        node._read_excel_via_fs(ctx, ctx.path, mode="full")


def test_load_excel_rejects_unknown_explicit_dtype_column(monkeypatch):
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/file.xlsx",
        dtypes={"ammount": "Float64"},
    )
    ctx = _make_smb_context("smb://fileserver:445/shared/reports/file.xlsx")

    monkeypatch.setattr(
        pd,
        "read_excel",
        lambda _file_obj, **_kwargs: pd.DataFrame({"amount": pd.Series([39.01], dtype="Float64")}),
    )

    with pytest.raises(ValueError, match="absent from the selected sheet: ammount"):
        node._read_excel_via_fs(ctx, ctx.path, mode="full")


def test_load_excel_rejects_unsupported_explicit_dtype():
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/file.xlsx",
        dtypes={"amount": "not-a-real-dtype"},
    )

    with pytest.raises(ValueError, match="Unsupported dtype 'not-a-real-dtype'"):
        node._read_excel_kwargs()


@pytest.mark.parametrize(
    ("separator_kwargs", "error_message"),
    [
        ({"decimal": ""}, "decimal separator must be exactly one character"),
        ({"decimal": ".."}, "decimal separator must be exactly one character"),
        ({"thousands": ""}, "thousands separator must be exactly one character"),
        ({"thousands": "  "}, "thousands separator must be exactly one character"),
        (
            {"thousands": ",", "decimal": ","},
            "thousands and decimal separators must be different",
        ),
    ],
)
def test_load_excel_rejects_invalid_numeric_separators(
    separator_kwargs,
    error_message,
):
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/file.xlsx",
        **separator_kwargs,
    )

    with pytest.raises(ValueError, match=error_message):
        node._read_excel_kwargs()


def test_load_excel_normalizes_only_numeric_columns_without_explicit_dtype():
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/file.xlsx",
    )
    source = pd.DataFrame(
        {
            "amount": pd.Series([1, 2], dtype="Int64"),
            "name": pd.Series(["a", "b"], dtype="string"),
            "active": pd.Series([True, False], dtype="boolean"),
            "created_at": pd.to_datetime(["2026-01-01", "2026-01-02"]),
        }
    )

    result = node._normalize_dataframe_dtypes(source)

    assert str(result["amount"].dtype) == "Float64"
    assert str(result["name"].dtype) == "string"
    assert str(result["active"].dtype) == "boolean"
    assert pd.api.types.is_datetime64_any_dtype(result["created_at"].dtype)


def test_load_excel_process_aligns_to_first_file_schema(monkeypatch):
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/*.xlsx",
    )
    files = [
        "smb://fileserver:445/shared/reports/a.xlsx",
        "smb://fileserver:445/shared/reports/b.xlsx",
    ]
    ctx = _make_smb_context(
        "smb://fileserver:445/shared/reports/*.xlsx",
        fs=_FakeSMBFS(glob_result=["/shared/reports/a.xlsx", "/shared/reports/b.xlsx"]),
    )

    monkeypatch.setattr(node, "_get_fs_context", lambda **_kwargs: ctx)

    def fake_read_excel(file_obj, **kwargs):
        path = getattr(file_obj, "path", None)
        if kwargs.get("nrows") == 32:
            return pd.DataFrame(
                {"id": pd.Series([1], dtype="Int64"), "name": pd.Series(["a"], dtype="string")}
            )
        if path == files[0]:
            return pd.DataFrame(
                {"id": pd.Series([1], dtype="Int64"), "name": pd.Series(["a"], dtype="string")}
            )
        return pd.DataFrame(
            {"name": pd.Series(["b"], dtype="string"), "id": pd.Series([2], dtype="Int64")}
        )

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    node.process()
    result = node.output.compute().reset_index(drop=True)

    assert list(result.columns) == ["id", "name"]
    assert result.to_dict(orient="records") == [
        {"id": 1, "name": "a"},
        {"id": 2, "name": "b"},
    ]


def test_load_excel_process_uses_fresh_ftp_fs_for_each_read(monkeypatch):
    created_fs_ids = []
    ftp_get_calls = []
    local_reads = []
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/*.xlsx",
        thousands=" ",
        decimal=",",
    )
    files = [
        "ftp://ftp.local:2121/reports/a.xlsx",
        "ftp://ftp.local:2121/reports/b.xlsx",
    ]
    base_ctx = _make_ftp_context(
        "ftp://ftp.local:2121/reports/*.xlsx",
        fs=_FakeFTPFS(fs_id="shared", glob_result=["/reports/a.xlsx", "/reports/b.xlsx"]),
    )

    monkeypatch.setattr(node, "_get_fs_context", lambda **_kwargs: base_ctx)

    def fake_filesystem(protocol: str, **storage_options):
        fs_id = f"ftp-fs-{len(created_fs_ids) + 1}"
        created_fs_ids.append((fs_id, protocol, storage_options))

        class _TrackingFTPFS(_FakeFTPFS):
            def get_file(self, remote_path: str, local_path: str) -> None:
                ftp_get_calls.append((remote_path, self.fs_id))
                restored_path = f"ftp://ftp.local:2121{remote_path}"
                Path(local_path).write_bytes(restored_path.encode("utf-8"))

        return _TrackingFTPFS(fs_id=fs_id)

    def fake_read_excel(file_obj, **kwargs):
        assert isinstance(file_obj, str)
        assert Path(file_obj).exists()
        assert kwargs["thousands"] == " "
        assert kwargs["decimal"] == ","
        assert "#ССЫЛКА!" in kwargs["na_values"]
        source_path = Path(file_obj).read_bytes().decode("utf-8")
        local_reads.append((source_path, kwargs.get("nrows")))
        if kwargs.get("nrows") == 32:
            return pd.DataFrame(
                {"id": pd.Series([1], dtype="Int64"), "name": pd.Series(["a"], dtype="string")}
            )
        if source_path == files[0]:
            return pd.DataFrame(
                {"id": pd.Series([1], dtype="Int64"), "name": pd.Series(["a"], dtype="string")}
            )
        return pd.DataFrame(
            {"id": pd.Series([2.5], dtype="Float64"), "name": pd.Series(["b"], dtype="string")}
        )

    monkeypatch.setattr("src.nodes.extract._shared.ftp_file.fsspec.filesystem", fake_filesystem)
    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    node.process()
    result = node.output.compute().reset_index(drop=True)

    assert list(result.columns) == ["id", "name"]
    assert str(result["id"].dtype) == "Float64"
    assert result.to_dict(orient="records") == [
        {"id": 1.0, "name": "a"},
        {"id": 2.5, "name": "b"},
    ]
    assert len(ftp_get_calls) == 3
    assert len({fs_id for _, fs_id in ftp_get_calls}) == 3
    assert Counter(path for path, _ in ftp_get_calls) == Counter(
        {
            "/reports/a.xlsx": 2,
            "/reports/b.xlsx": 1,
        }
    )
    assert Counter(local_reads) == Counter(
        {
            (files[0], 32): 1,
            (files[0], None): 1,
            (files[1], None): 1,
        }
    )
    assert all(protocol == "ftp" for _, protocol, _ in created_fs_ids)
    assert all(
        storage_options == base_ctx.storage_options for _, _, storage_options in created_fs_ids
    )


def test_load_excel_infer_metadata_downloads_ftp_file_to_temp(monkeypatch, tmp_path):
    captured = {}
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/file.xlsx",
    )
    ctx = _make_ftp_context("ftp://ftp.local:2121/reports/file.xlsx")

    monkeypatch.setattr(node, "_get_fs_context", lambda **_kwargs: ctx)
    monkeypatch.setattr("src.nodes.extract._shared.ftp_file.tempfile.tempdir", str(tmp_path))
    monkeypatch.setattr(
        "src.nodes.extract._shared.ftp_file.fsspec.filesystem",
        lambda protocol, **storage_options: _FakeFTPFS(fs_id="ftp-fs-1"),
    )

    def fake_read_excel(file_obj, **kwargs):
        captured["path"] = file_obj
        captured["kwargs"] = kwargs
        assert isinstance(file_obj, str)
        assert str(tmp_path) in file_obj
        assert Path(file_obj).exists()
        return pd.DataFrame(
            {"id": pd.Series([1], dtype="Int64"), "name": pd.Series(["x"], dtype="string")}
        )

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    metadata = node.infer_metadata()

    assert captured["kwargs"]["nrows"] == 32
    assert metadata["output"].columns[0].name == "id"
    assert metadata["output"].columns[1].name == "name"
    assert not Path(captured["path"]).exists()


def test_load_excel_ftp_temp_file_is_removed_after_success(monkeypatch, tmp_path):
    captured = {}
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/file.xlsx",
    )
    ctx = _make_ftp_context("ftp://ftp.local:2121/reports/file.xlsx")

    monkeypatch.setattr("src.nodes.extract._shared.ftp_file.tempfile.tempdir", str(tmp_path))
    monkeypatch.setattr(
        "src.nodes.extract._shared.ftp_file.fsspec.filesystem",
        lambda protocol, **storage_options: _FakeFTPFS(fs_id="ftp-fs-1"),
    )

    def fake_read_excel(file_obj, **kwargs):
        captured["path"] = file_obj
        assert isinstance(file_obj, str)
        assert Path(file_obj).exists()
        return pd.DataFrame({"id": pd.Series([1], dtype="Int64")})

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    result = node._read_excel_via_fs(ctx, ctx.path, mode="full")

    assert list(result.columns) == ["id"]
    assert not Path(captured["path"]).exists()


def test_load_excel_ftp_temp_file_is_removed_after_failure(monkeypatch, tmp_path):
    captured = {}
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/file.xlsx",
    )
    ctx = _make_ftp_context("ftp://ftp.local:2121/reports/file.xlsx")

    monkeypatch.setattr("src.nodes.extract._shared.ftp_file.tempfile.tempdir", str(tmp_path))
    monkeypatch.setattr(
        "src.nodes.extract._shared.ftp_file.fsspec.filesystem",
        lambda protocol, **storage_options: _FakeFTPFS(fs_id="ftp-fs-1"),
    )

    def fake_read_excel(file_obj, **kwargs):
        captured["path"] = file_obj
        assert isinstance(file_obj, str)
        assert Path(file_obj).exists()
        raise ValueError("broken excel")

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    with pytest.raises(ValueError, match="broken excel"):
        node._read_excel_via_fs(ctx, ctx.path, mode="full")

    assert not Path(captured["path"]).exists()


def test_load_excel_read_timeout_raises_timeout_error(monkeypatch):
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/file.xlsx",
        read_timeout_sec=1,
    )

    class _FakeFuture:
        def result(self, timeout=None):
            raise TimeoutError()

        def cancel(self):
            return True

    class _FakeExecutor:
        def __init__(self, *args, **kwargs):
            self.submitted = None
            self.shutdown_calls = []

        def submit(self, fn):
            self.submitted = fn
            return _FakeFuture()

        def shutdown(self, wait, cancel_futures):
            self.shutdown_calls.append((wait, cancel_futures))

    monkeypatch.setattr("src.nodes.extract.load_excel.node.ThreadPoolExecutor", _FakeExecutor)
    monkeypatch.setattr(
        "src.nodes.extract.load_excel.node.FuturesTimeoutError",
        TimeoutError,
    )

    def fake_frame():
        return pd.DataFrame()

    with pytest.raises(TimeoutError, match="Timed out reading Excel in metadata mode"):
        node._run_with_timeout(fake_frame, mode="metadata", path="reports/file.xlsx")


def test_load_excel_process_passes_timeout_to_fs_context(monkeypatch):
    captured = {}
    node = LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/file.xlsx",
        read_timeout_sec=11,
    )
    ctx = _make_smb_context("smb://fileserver:445/shared/reports/file.xlsx")

    def fake_get_fs_context(**kwargs):
        captured.update(kwargs)
        return ctx

    def fake_read_excel(_file_obj, **_kwargs):
        return pd.DataFrame({"id": pd.Series([1], dtype="Int64")})

    monkeypatch.setattr(node, "_get_fs_context", fake_get_fs_context)
    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    node.process()

    assert captured["timeout_sec"] == 11
    assert captured["ftp_block_size"] == 1024 * 1024
