from types import SimpleNamespace

import pytest
from sqlalchemy import URL

from core.types import FsCtx

from src.node_dsl.runtime import (
    resolve_file_fs_context,
    resolve_sql_engine,
    restore_file_url,
    validate_connection_record,
)
from src.node_dsl.runtime.integrations.file_connection.overrides import (
    ResolvedFTPConnectionOverrides,
    ResolvedS3ConnectionOverrides,
    ResolvedSFTPConnectionOverrides,
)


class _FakeSFTPProperties:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        initial_directory: str,
        private_key_path: str | None,
        allow_agent: bool,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.initial_directory = initial_directory
        self.private_key_path = private_key_path
        self.allow_agent = allow_agent


def _make_record_like_sql_connection():
    return SimpleNamespace(
        name="Legacy postgres",
        kind="sql",
        type="postgres",
        driver=None,
        driver_options=None,
        properties={
            "host": "localhost",
            "port": 5432,
            "username": "postgres",
            "database": "postgres",
        },
        secrets={"password": "secret"},
    )


def _make_record_like_smb_connection():
    return SimpleNamespace(
        name="Shared files",
        kind="file",
        type="smbprotocol",
        driver=None,
        driver_options=None,
        properties={
            "host": "fileserver",
            "port": 445,
            "share": "shared",
            "username": "reader",
        },
        secrets={"password": "secret"},
    )


def _make_record_like_file_connection(connection_type: str):
    return SimpleNamespace(
        name=f"{connection_type} connection",
        kind="file",
        type=connection_type,
        driver=None,
        driver_options=None,
        properties={},
        secrets={},
    )


@pytest.mark.parametrize(
    ("protocol", "url_root", "path", "expected"),
    [
        (
            "s3",
            "s3://",
            "dvt/denvic_folder/report.xlsx",
            "s3://dvt/denvic_folder/report.xlsx",
        ),
        (
            "smb",
            "smb://fileserver:445",
            "/shared/reports/report.xlsx",
            "smb://fileserver:445/shared/reports/report.xlsx",
        ),
        (
            "sftp",
            "sftp://fileserver:22",
            "/incoming/report.xlsx",
            "sftp://fileserver:22/incoming/report.xlsx",
        ),
        (
            "ftp",
            "ftp://fileserver:21/",
            "/incoming/report.xlsx",
            "ftp://fileserver:21/incoming/report.xlsx",
        ),
        (
            "dvtfiles",
            "dvtfiles://project-1",
            "reports/report.xlsx",
            "dvtfiles://project-1/reports/report.xlsx",
        ),
        (
            "memory",
            None,
            "/reports/report.xlsx",
            "memory://reports/report.xlsx",
        ),
        (
            "s3",
            "s3://",
            "s3://other-bucket/report.xlsx",
            "s3://other-bucket/report.xlsx",
        ),
    ],
)
def test_restore_file_url(
    protocol: str,
    url_root: str | None,
    path: str,
    expected: str,
) -> None:
    ctx = FsCtx(
        fs=None,
        protocol=protocol,
        path="",
        storage_options={},
        url_root=url_root,
    )

    assert restore_file_url(ctx, path) == expected


def test_validate_connection_record_normalizes_missing_optional_fields():
    validated = validate_connection_record(_make_record_like_sql_connection())

    assert validated.name == "Legacy postgres"
    assert validated.labels == {}
    assert validated.metadata == {}
    assert validated.extra == {}


def test_resolve_sql_engine_accepts_record_like_without_optional_fields(monkeypatch):
    captured = {}

    def fake_create_engine(url):
        captured["url"] = url
        return "fake-engine"

    monkeypatch.setattr("src.node_dsl.runtime.connections.create_engine", fake_create_engine)

    result = resolve_sql_engine(_make_record_like_sql_connection())

    assert result == "fake-engine"
    assert isinstance(captured["url"], URL | str)
    assert "postgres" in str(captured["url"])


def test_resolve_file_fs_context_builds_smb_url_and_storage_options():
    fs_ctx = resolve_file_fs_context(
        _make_record_like_smb_connection(),
        path="reports/export.csv",
        create_fs=False,
        timeout_sec=17,
    )

    assert fs_ctx.protocol == "smb"
    assert fs_ctx.path == "smb://fileserver:445/shared/reports/export.csv"
    assert fs_ctx.storage_options == {
        "host": "fileserver",
        "port": 445,
        "username": "reader",
        "password": "secret",
        "timeout": 17,
    }
    assert fs_ctx.url_root == "smb://fileserver:445"


def test_resolve_file_fs_context_builds_dvt_service_files_url_from_mapping():
    fs_ctx = resolve_file_fs_context(
        {
            "name": "Node file",
            "kind": "file",
            "type": "dvt_service_files",
            "properties": {
                "organization_id": "org-1",
                "project_id": "project-1",
                "root_prefix": "node-inputs/node-1/file",
            },
            "secrets": {},
        },
        path="data.csv",
        create_fs=False,
    )

    assert fs_ctx.protocol == "dvtfiles"
    assert fs_ctx.path == "dvtfiles://project-1/data.csv"
    assert fs_ctx.storage_options == {
        "organization_id": "org-1",
        "project_id": "project-1",
        "root_prefix": "node-inputs/node-1/file",
    }
    assert fs_ctx.url_root == "dvtfiles://project-1"


def test_resolve_file_fs_context_applies_s3_overrides(monkeypatch):
    monkeypatch.setattr(
        "src.node_dsl.runtime.connections.validate_connection_record",
        lambda _record: SimpleNamespace(
            properties=SimpleNamespace(
                bucket="source-bucket",
                region_name="ru-central1",
                endpoint_url="https://s3.local",
                use_ssl=False,
                verify=True,
                path_style=True,
                prefix="source-prefix",
                access_token_id="key",
                access_token_key="secret",
                signature_version=None,
                session_token=None,
            ),
            secrets=SimpleNamespace(
                access_token_id="key",
                access_token_key="secret",
                session_token=None,
            ),
        ),
    )

    fs_ctx = resolve_file_fs_context(
        _make_record_like_file_connection("s3"),
        path="reports/export.csv",
        create_fs=False,
        overrides=ResolvedS3ConnectionOverrides(
            bucket="override-bucket",
            prefix="override-prefix",
            verify=False,
        ),
    )

    assert fs_ctx.protocol == "s3"
    assert fs_ctx.path == "s3://override-bucket/override-prefix/reports/export.csv"
    assert fs_ctx.storage_options["client_kwargs"]["verify"] is False
    assert fs_ctx.url_root == "s3://"


def test_resolve_file_fs_context_allows_explicit_s3_prefix_reset(monkeypatch):
    monkeypatch.setattr(
        "src.node_dsl.runtime.connections.validate_connection_record",
        lambda _record: SimpleNamespace(
            properties=SimpleNamespace(
                bucket="source-bucket",
                region_name="ru-central1",
                endpoint_url="https://s3.local",
                use_ssl=False,
                verify=True,
                path_style=True,
                prefix="source-prefix",
                access_token_id="key",
                access_token_key="secret",
                signature_version=None,
                session_token=None,
            ),
            secrets=SimpleNamespace(
                access_token_id="key",
                access_token_key="secret",
                session_token=None,
            ),
        ),
    )

    fs_ctx = resolve_file_fs_context(
        _make_record_like_file_connection("s3"),
        path="reports/export.csv",
        create_fs=False,
        overrides=ResolvedS3ConnectionOverrides(prefix=""),
    )

    assert fs_ctx.path == "s3://source-bucket/reports/export.csv"


def test_resolve_file_fs_context_uses_s3_connection_verify_when_not_overridden(monkeypatch):
    monkeypatch.setattr(
        "src.node_dsl.runtime.connections.validate_connection_record",
        lambda _record: SimpleNamespace(
            properties=SimpleNamespace(
                bucket="source-bucket",
                region_name="ru-central1",
                endpoint_url="https://s3.local",
                use_ssl=True,
                verify=False,
                path_style=True,
                prefix="source-prefix",
                access_token_id="key",
                access_token_key="secret",
                signature_version=None,
                session_token=None,
            ),
            secrets=SimpleNamespace(
                access_token_id="key",
                access_token_key="secret",
                session_token=None,
            ),
        ),
    )

    fs_ctx = resolve_file_fs_context(
        _make_record_like_file_connection("s3"),
        path="reports/export.csv",
        create_fs=False,
    )

    assert fs_ctx.storage_options["client_kwargs"]["verify"] is False


def test_resolve_file_fs_context_applies_s3_timeout(monkeypatch):
    monkeypatch.setattr(
        "src.node_dsl.runtime.connections.validate_connection_record",
        lambda _record: SimpleNamespace(
            properties=SimpleNamespace(
                bucket="source-bucket",
                region_name="ru-central1",
                endpoint_url="https://s3.local",
                use_ssl=False,
                verify=True,
                path_style=True,
                prefix="source-prefix",
                access_token_id="key",
                access_token_key="secret",
                signature_version=None,
                session_token=None,
            ),
            secrets=SimpleNamespace(
                access_token_id="key",
                access_token_key="secret",
                session_token=None,
            ),
        ),
    )

    fs_ctx = resolve_file_fs_context(
        _make_record_like_file_connection("s3"),
        path="reports/export.csv",
        create_fs=False,
        timeout_sec=23,
    )

    assert fs_ctx.storage_options["config_kwargs"]["connect_timeout"] == 23
    assert fs_ctx.storage_options["config_kwargs"]["read_timeout"] == 23


def test_resolve_file_fs_context_applies_ftp_overrides(monkeypatch):
    monkeypatch.setattr(
        "src.node_dsl.runtime.connections.validate_connection_record",
        lambda _record: SimpleNamespace(
            properties=SimpleNamespace(
                host="ftp.local",
                port=2121,
                username="ftpuser",
                anonymous=False,
                mode="ftp",
                encoding="utf-8",
                initial_directory="/incoming",
                certfile=None,
                keyfile=None,
                max_items=100,
            ),
            secrets=SimpleNamespace(password="secret"),
        ),
    )

    fs_ctx = resolve_file_fs_context(
        _make_record_like_file_connection("ftp"),
        path="reports/export.csv",
        create_fs=False,
        timeout_sec=19,
        overrides=ResolvedFTPConnectionOverrides(initial_directory=""),
    )

    assert fs_ctx.protocol == "ftp"
    assert fs_ctx.path == "ftp://ftp.local:2121/reports/export.csv"
    assert fs_ctx.storage_options["timeout"] == 19


def test_resolve_file_fs_context_applies_sftp_overrides(monkeypatch):
    monkeypatch.setattr("src.node_dsl.runtime.connections.SFTPProperties", _FakeSFTPProperties)
    monkeypatch.setattr(
        "src.node_dsl.runtime.connections.validate_connection_record",
        lambda _record: SimpleNamespace(
            properties=_FakeSFTPProperties(
                host="sftp.local",
                port=22,
                username="sftpuser",
                initial_directory="/incoming",
                private_key_path=None,
                allow_agent=False,
            ),
            secrets=SimpleNamespace(password="secret"),
        ),
    )

    fs_ctx = resolve_file_fs_context(
        _make_record_like_file_connection("sftp"),
        path="reports/export.csv",
        create_fs=False,
        overrides=ResolvedSFTPConnectionOverrides(initial_directory="/override"),
    )

    assert fs_ctx.protocol == "sftp"
    assert fs_ctx.path == "sftp://sftp.local:22/override/reports/export.csv"
