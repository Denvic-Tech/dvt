from __future__ import annotations

from contextlib import contextmanager

from core.metadata import ftp_metadata
from core.metadata.ftp_metadata import (
    _make_connection_string,
    load_ftp_metadata,
    load_ftp_path_metadata,
)


def test_make_connection_string_masks_password() -> None:
    conn_str = _make_connection_string("ftp.local", 2121, "ftpuser", "secret123")
    assert conn_str == "ftp://ftpuser:secr***@ftp.local:2121"


def test_load_ftp_metadata_basic(monkeypatch) -> None:
    ftp_metadata.ftp_metadata_cache.clear()
    ftp_metadata.ftp_path_metadata_cache.clear()
    captured_kwargs = {}

    class FakeClient:
        def mlsd(self, current_path: str):
            assert current_path == "/incoming"
            return [
                ("folder", {"type": "dir", "perm": "755"}),
                ("report.csv", {"type": "file", "size": "12", "perm": "644"}),
            ]

    @contextmanager
    def fake_build_ftp_client(**kwargs):
        captured_kwargs.update(kwargs)
        yield FakeClient()

    monkeypatch.setattr(ftp_metadata, "_build_ftp_client", fake_build_ftp_client)

    meta = load_ftp_metadata(
        connection_id="conn-ftp-1",
        host="ftp.local",
        port=2121,
        mode="ftp",
        username="ftpuser",
        password="ftppassword",
        anonymous=False,
        encoding="utf-8",
        initial_directory="/incoming",
        certfile=None,
        keyfile=None,
        max_items=100,
    )

    assert captured_kwargs["host"] == "ftp.local"
    assert captured_kwargs["port"] == 2121
    assert captured_kwargs["initial_directory"] == "/incoming"
    assert captured_kwargs["anonymous"] is False
    assert meta.connection_id == "conn-ftp-1"
    assert meta.connection_string == "ftp://ftpuser:ftpp***@ftp.local:2121"
    assert meta.directory is not None
    assert meta.directory.current_path == "/incoming"
    assert meta.directory.files_count == 1
    assert meta.directory.folders_count == 1
    assert meta.directory.total_size == 12


def test_load_ftp_path_metadata_returns_nodes(monkeypatch) -> None:
    ftp_metadata.ftp_path_metadata_cache.clear()

    class FakeClient:
        def mlsd(self, current_path: str):
            assert current_path == "/nested"
            return [
                ("folder", {"type": "dir", "unix.mode": "755"}),
                ("file.txt", {"type": "file", "size": "5", "perm": "644"}),
            ]

    @contextmanager
    def fake_build_ftp_client(**kwargs):
        assert kwargs["initial_directory"] == "/"
        yield FakeClient()

    monkeypatch.setattr(ftp_metadata, "_build_ftp_client", fake_build_ftp_client)

    nodes, is_truncated, next_token = load_ftp_path_metadata(
        host="ftp.local",
        port=2121,
        mode="ftp",
        username="ftpuser",
        password="ftppassword",
        anonymous=False,
        encoding="utf-8",
        initial_directory="/",
        certfile=None,
        keyfile=None,
        path="nested",
        max_items=1000,
    )

    assert is_truncated is False
    assert next_token is None
    assert [node.name for node in nodes] == ["folder", "file.txt"]
    assert [node.path for node in nodes] == ["/nested/folder", "/nested/file.txt"]


def test_create_ftp_client_uses_anonymous_credentials(monkeypatch) -> None:
    captured = {}

    class FakeFTP:
        def __init__(self, *, timeout: int, encoding: str) -> None:
            captured["timeout"] = timeout
            captured["encoding"] = encoding

        def connect(self, host: str, port: int) -> None:
            captured["connect"] = (host, port)

        def login(self, *, user: str, passwd: str) -> None:
            captured["login"] = (user, passwd)

        def set_pasv(self, enabled: bool) -> None:
            captured["pasv"] = enabled

        def cwd(self, path: str) -> None:
            captured["cwd"] = path

        def quit(self) -> None:
            captured["closed"] = True

    monkeypatch.setattr(ftp_metadata, "FTP", FakeFTP)

    client = ftp_metadata._create_ftp_client(
        host="ftp.local",
        port=21,
        username=None,
        password=None,
        anonymous=True,
        initial_directory="/pub",
    )
    ftp_metadata._close_ftp_client(client)

    assert captured["connect"] == ("ftp.local", 21)
    assert captured["login"] == ("anonymous", "")
    assert captured["pasv"] is True
    assert captured["cwd"] == "/pub"
    assert captured["closed"] is True
