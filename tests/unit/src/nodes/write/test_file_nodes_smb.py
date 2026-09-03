from contextlib import contextmanager
from io import BytesIO

import dask.dataframe as dd
import fsspec
import pandas as pd

from core.types import FsCtx

from src.nodes.write.save_csv import SaveCSV
from src.nodes.write.save_excel import SaveExcel
from src.nodes.write.save_parquet import SaveParquet


class _FakeSMBFS:
    def __init__(self) -> None:
        self.open_calls: list[tuple[str, str]] = []

    @contextmanager
    def open(self, path: str, mode: str):
        self.open_calls.append((path, mode))
        yield BytesIO()


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


def test_save_csv_writes_to_smb_path(monkeypatch):
    captured = {}
    ddf = dd.from_pandas(pd.DataFrame({"id": [1, 2]}), npartitions=1)
    node = SaveCSV(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="save-csv-node",
        connection=object(),
        df=ddf,
        path="reports/export.csv",
    )

    monkeypatch.setattr(
        node,
        "_get_fs_context",
        lambda **_kwargs: _make_smb_context("smb://fileserver:445/shared/reports/export.csv"),
    )
    monkeypatch.setattr(
        dd.DataFrame,
        "to_csv",
        lambda self, path, **kwargs: captured.update({"path": path, "kwargs": kwargs}),
        raising=True,
    )

    node.process()

    assert captured["path"] == "smb://fileserver:445/shared/reports/export.csv"
    assert captured["kwargs"]["storage_options"]["host"] == "fileserver"


def test_save_parquet_writes_to_smb_path(monkeypatch):
    captured = {}
    ddf = dd.from_pandas(pd.DataFrame({"id": [1, 2]}), npartitions=1)
    node = SaveParquet(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="save-parquet-node",
        connection=object(),
        df=ddf,
        path="reports/export.parquet",
        mode="create",
        compatibility_mode="legacy",
    )

    monkeypatch.setattr(
        node,
        "_get_fs_context",
        lambda: _make_smb_context("smb://fileserver:445/shared/reports/export.parquet"),
    )
    monkeypatch.setattr(
        dd.DataFrame,
        "to_parquet",
        lambda self, path, **kwargs: captured.update({"path": path, "kwargs": kwargs}),
        raising=True,
    )

    node.process()

    assert captured["path"] == "smb://fileserver:445/shared/reports/export.parquet"
    assert captured["kwargs"]["storage_options"]["host"] == "fileserver"


def test_save_parquet_new_mode_writes_exact_simple_and_advanced_smb_layout(monkeypatch):
    fs = fsspec.filesystem("memory")
    fs.store.clear()
    ddf = dd.from_pandas(pd.DataFrame({"id": [1, 2, 3]}), npartitions=2)

    simple = SaveParquet(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="save-parquet-simple",
        connection=object(),
        df=ddf,
        path="reports/export.parquet",
        mode="create",
        compatibility_mode="new",
    )
    monkeypatch.setattr(
        "src.node_dsl.runtime.integrations.file_connection.mixin.FileConnectionInputMixin._get_fs_context",
        lambda _self, *, path=None, **_kwargs: _make_smb_context(
            f"/shared/{path}",
            fs=fs,
        ),
    )
    simple.process()

    advanced = SaveParquet(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="save-parquet-advanced",
        connection=object(),
        df=ddf,
        path="reports/export",
        mode="create",
        compatibility_mode="new",
        filename_template="<increment>.parquet",
    )
    advanced.process()

    assert sorted(fs.find("/shared/reports")) == [
        "/shared/reports/export.parquet",
        "/shared/reports/export/00000.parquet",
        "/shared/reports/export/00001.parquet",
    ]


def test_save_excel_writes_single_file_to_smb_path(monkeypatch):
    captured = {}
    fake_fs = _FakeSMBFS()
    ddf = dd.from_pandas(pd.DataFrame({"id": [1, 2]}), npartitions=1)
    node = SaveExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="save-excel-node",
        connection=object(),
        df=ddf,
        path="reports/export.xlsx",
    )

    monkeypatch.setattr(
        node,
        "_get_fs_context",
        lambda **_kwargs: _make_smb_context("smb://fileserver:445/shared", fs=fake_fs),
    )

    class _DummyExcelWriter:
        def __init__(self, file_obj, engine=None):
            captured["engine"] = engine
            captured["file_obj"] = file_obj

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(pd, "ExcelWriter", _DummyExcelWriter)
    monkeypatch.setattr(
        pd.DataFrame,
        "to_excel",
        lambda self, writer, **kwargs: captured.update({"sheet_name": kwargs["sheet_name"]}),
        raising=True,
    )

    node.process()

    assert fake_fs.open_calls == [
        ("smb://fileserver:445/shared/reports/export.xlsx", "wb")
    ]
    assert captured["engine"] == "openpyxl"
    assert captured["sheet_name"] == "Sheet1"
