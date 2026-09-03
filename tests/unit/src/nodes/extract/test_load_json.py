from contextlib import contextmanager
from io import BytesIO

import pytest

from core.types import FsCtx, JSONMetadata

from src.nodes.extract.load_json import LoadJSON


class _FakeSMBFS:
    def __init__(self, *, glob_result=None, exists_result=False, file_map=None):
        self._glob_result = list(glob_result or [])
        self._exists_result = exists_result
        self._file_map = dict(file_map or {})
        self.opened_paths: list[str] = []

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

    def info(self, path: str):
        if not self._exists_result:
            raise FileNotFoundError(path)
        return {"name": path, "type": "file"}

    @contextmanager
    def open(self, path: str, mode: str):
        self.opened_paths.append(path)
        if path not in self._file_map:
            raise FileNotFoundError(path)
        yield BytesIO(self._file_map[path])


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


def _make_node(path: str) -> LoadJSON:
    return LoadJSON(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-json-node",
        connection=object(),
        path=path,
    )


def test_load_json_processes_single_object_document(monkeypatch) -> None:
    node = _make_node("reports/data.json")
    fs = _FakeSMBFS(
        exists_result=True,
        file_map={
            "smb://fileserver:445/shared/reports/data.json": b'{"id": 1, "name": "Alice"}',
        },
    )

    monkeypatch.setattr(
        node,
        "_get_fs_context",
        lambda **_kwargs: _make_smb_context("smb://fileserver:445/shared/reports/data.json", fs=fs),
    )

    node.process()

    assert node.output == {"id": 1, "name": "Alice"}
    assert fs.opened_paths == ["smb://fileserver:445/shared/reports/data.json"]


def test_load_json_processes_single_array_document(monkeypatch) -> None:
    node = _make_node("reports/data.json")
    fs = _FakeSMBFS(
        exists_result=True,
        file_map={
            "smb://fileserver:445/shared/reports/data.json": b'[{"id": 1}, {"id": 2}]',
        },
    )

    monkeypatch.setattr(
        node,
        "_get_fs_context",
        lambda **_kwargs: _make_smb_context("smb://fileserver:445/shared/reports/data.json", fs=fs),
    )

    node.process()

    assert node.output == [{"id": 1}, {"id": 2}]


def test_load_json_glob_returns_sorted_list_of_documents(monkeypatch) -> None:
    node = _make_node("reports/*.json")
    fs = _FakeSMBFS(
        glob_result=["/shared/reports/b.json", "/shared/reports/a.json"],
        file_map={
            "smb://fileserver:445/shared/reports/a.json": b'{"id": "a"}',
            "smb://fileserver:445/shared/reports/b.json": b'{"id": "b"}',
        },
    )

    monkeypatch.setattr(
        node,
        "_get_fs_context",
        lambda **_kwargs: _make_smb_context("smb://fileserver:445/shared/reports/*.json", fs=fs),
    )

    node.process()

    assert node.output == [{"id": "a"}, {"id": "b"}]
    assert fs.opened_paths == [
        "smb://fileserver:445/shared/reports/a.json",
        "smb://fileserver:445/shared/reports/b.json",
    ]


def test_load_json_s3_glob_opens_valid_full_urls_in_sorted_order(monkeypatch) -> None:
    node = _make_node("reports/*.json")
    fs = _FakeS3FS(
        glob_result=["dvt/reports/b.json", "dvt/reports/a.json"],
        file_map={
            "s3://dvt/reports/a.json": b'{"id": "a"}',
            "s3://dvt/reports/b.json": b'{"id": "b"}',
        },
    )

    monkeypatch.setattr(
        node,
        "_get_fs_context",
        lambda **_kwargs: _make_s3_context("s3://dvt/reports/*.json", fs=fs),
    )

    node.process()

    assert node.output == [{"id": "a"}, {"id": "b"}]
    assert fs.opened_paths == [
        "s3://dvt/reports/a.json",
        "s3://dvt/reports/b.json",
    ]


def test_load_json_raises_when_files_are_missing(monkeypatch) -> None:
    node = _make_node("reports/missing.json")

    monkeypatch.setattr(
        node,
        "_get_fs_context",
        lambda **_kwargs: _make_smb_context("smb://fileserver:445/shared/reports/missing.json"),
    )

    with pytest.raises(FileNotFoundError, match="JSON file\\(s\\) not found"):
        node.process()


def test_load_json_raises_clear_error_for_invalid_json(monkeypatch) -> None:
    node = _make_node("reports/bad.json")
    fs = _FakeSMBFS(
        exists_result=True,
        file_map={
            "smb://fileserver:445/shared/reports/bad.json": b'{"broken": }',
        },
    )

    monkeypatch.setattr(
        node,
        "_get_fs_context",
        lambda **_kwargs: _make_smb_context("smb://fileserver:445/shared/reports/bad.json", fs=fs),
    )

    with pytest.raises(ValueError, match="Invalid JSON in file 'smb://fileserver:445/shared/reports/bad.json'"):
        node.process()


def test_load_json_infer_metadata_returns_json_metadata(monkeypatch) -> None:
    node = _make_node("reports/data.json")
    fs = _FakeSMBFS(
        exists_result=True,
        file_map={
            "smb://fileserver:445/shared/reports/data.json": b'{"items": [{"id": 1}, {"id": 2}]}',
        },
    )

    monkeypatch.setattr(
        node,
        "_get_fs_context",
        lambda **_kwargs: _make_smb_context("smb://fileserver:445/shared/reports/data.json", fs=fs),
    )

    metadata = node.infer_metadata()

    assert "output" in metadata
    assert isinstance(metadata["output"], JSONMetadata)
    assert metadata["output"].root is not None
