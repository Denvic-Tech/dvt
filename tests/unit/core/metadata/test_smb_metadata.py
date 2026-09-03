from datetime import datetime

from core.metadata import smb_metadata
from core.metadata.smb_metadata import (
    _make_connection_string,
    load_smb_metadata,
    load_smb_path_metadata,
)


def test_make_connection_string_for_smb() -> None:
    conn_str = _make_connection_string("fileserver.local", 445, "shared", "reader")
    assert conn_str == "smb://reader@fileserver.local:445/shared"


def test_load_smb_metadata_basic(monkeypatch) -> None:
    smb_metadata.smb_metadata_cache.clear()
    smb_metadata.smb_path_metadata_cache.clear()
    captured_kwargs = {}

    class FakeFS:
        def ls(self, path: str, detail: bool = True):
            assert path == "/shared"
            assert detail is True
            return [
                {"name": "/shared/folder", "type": "directory", "size": 0},
                {
                    "name": "/shared/report.csv",
                    "type": "file",
                    "size": 12,
                    "mtime": datetime(2024, 1, 1),
                },
            ]

    def fake_filesystem(protocol: str, **kwargs):
        captured_kwargs["protocol"] = protocol
        captured_kwargs.update(kwargs)
        return FakeFS()

    monkeypatch.setattr(smb_metadata.fsspec, "filesystem", fake_filesystem)

    meta = load_smb_metadata(
        connection_id="conn-smb-1",
        host="fileserver.local",
        port=445,
        share="shared",
        username="reader",
        password="secret",
        max_items=100,
    )

    assert captured_kwargs == {
        "protocol": "smb",
        "host": "fileserver.local",
        "port": 445,
        "username": "reader",
        "password": "secret",
    }
    assert meta.type == "SMB"
    assert meta.connection_id == "conn-smb-1"
    assert meta.connection_string == "smb://reader@fileserver.local:445/shared"
    assert meta.connection_prefix == "fileserver.local:445/shared"
    assert meta.share == "shared"
    assert meta.directory is not None
    assert meta.directory.share == "shared"
    assert meta.directory.files_count == 1
    assert meta.directory.folders_count == 1
    assert meta.directory.total_size == 12


def test_load_smb_path_metadata_returns_nodes(monkeypatch) -> None:
    smb_metadata.smb_path_metadata_cache.clear()

    class FakeFS:
        def ls(self, path: str, detail: bool = True):
            assert path == "/shared/nested"
            return [
                {"name": "/shared/nested/folder", "type": "directory", "size": 0},
                {"name": "/shared/nested/file.txt", "type": "file", "size": 5},
            ]

    monkeypatch.setattr(
        smb_metadata.fsspec,
        "filesystem",
        lambda protocol, **kwargs: FakeFS(),
    )

    nodes, is_truncated, next_token = load_smb_path_metadata(
        host="fileserver.local",
        port=445,
        share="shared",
        username="reader",
        password="secret",
        path="nested",
        max_items=1000,
    )

    assert is_truncated is False
    assert next_token is None
    assert [node.name for node in nodes] == ["folder", "file.txt"]
    assert [node.path for node in nodes] == ["nested/folder", "nested/file.txt"]
