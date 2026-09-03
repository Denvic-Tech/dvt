from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.gateway.routes.storage.deps import impl as deps_module
from src.modules.file_storage import (
    FileStorageFacade,
    ResolvedFTPStorageConnection,
    ResolvedSMBStorageConnection,
    ResolvedS3StorageConnection,
    ResolvedSFTPStorageConnection,
)
from src.modules.file_storage.flow.exceptions import (
    StorageConnectionNotFoundError,
    UnsupportedStorageBackendError,
)
from src.modules.file_storage.infra.clients import S3StorageClient


class _ResolvedConnection:
    def __init__(self, *, connection_type: str, properties: dict[str, object]) -> None:
        self.client = object()
        self.connection = SimpleNamespace(properties=properties)
        self.type = connection_type
        self.kind = "file"
        self.driver = None
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def test_map_resolved_connection_supports_storage_backends() -> None:
    s3_connection = deps_module._map_resolved_connection(
        _ResolvedConnection(
            connection_type="s3",
            properties={"bucket": "analytics", "prefix": "incoming"},
        )
    )
    ftp_connection = deps_module._map_resolved_connection(
        _ResolvedConnection(
            connection_type="ftp",
            properties={"initial_directory": "/uploads"},
        )
    )
    sftp_connection = deps_module._map_resolved_connection(
        _ResolvedConnection(
            connection_type="sftp",
            properties={"initial_directory": "/uploads"},
        )
    )
    smb_connection = deps_module._map_resolved_connection(
        _ResolvedConnection(
            connection_type="smbprotocol",
            properties={"initial_directory": "/uploads"},
        )
    )

    assert isinstance(s3_connection, ResolvedS3StorageConnection)
    assert isinstance(s3_connection.client, S3StorageClient)
    assert s3_connection.bucket == "analytics"
    assert s3_connection.prefix == "incoming"
    assert isinstance(ftp_connection, ResolvedFTPStorageConnection)
    assert ftp_connection.initial_directory == "/uploads"
    assert isinstance(sftp_connection, ResolvedSFTPStorageConnection)
    assert sftp_connection.initial_directory == "/uploads"
    assert isinstance(smb_connection, ResolvedSMBStorageConnection)
    assert smb_connection.initial_directory == "/uploads"


@pytest.mark.asyncio
async def test_get_file_storage_facade_translates_access_denied(monkeypatch) -> None:
    class _Denied(Exception):
        pass

    class _UseCase:
        async def execute(self, **_kwargs):
            raise _Denied()

    monkeypatch.setattr(deps_module, "AccessDeniedError", _Denied)
    monkeypatch.setattr(deps_module, "_build_resolve_connection_use_case", lambda: _UseCase())

    dependency = deps_module.get_file_storage_facade(
        connection_id="conn-1",
        user=SimpleNamespace(id="user-1", organization_id="org-1", role="admin"),
    )

    with pytest.raises(StorageConnectionNotFoundError, match="conn-1"):
        await anext(dependency)


@pytest.mark.asyncio
async def test_get_file_storage_facade_closes_resolved_client_on_mapping_error(monkeypatch) -> None:
    resolved = _ResolvedConnection(
        connection_type="postgres",
        properties={"database": "warehouse"},
    )

    class _UseCase:
        async def execute(self, **_kwargs):
            return resolved

    monkeypatch.setattr(deps_module, "_build_resolve_connection_use_case", lambda: _UseCase())

    dependency = deps_module.get_file_storage_facade(
        connection_id="conn-1",
        user=SimpleNamespace(id="user-1", organization_id="org-1", role="admin"),
    )

    with pytest.raises(UnsupportedStorageBackendError, match="postgres"):
        await anext(dependency)

    assert resolved.closed is True


@pytest.mark.asyncio
async def test_get_file_storage_facade_yields_bound_facade_and_closes_client(monkeypatch) -> None:
    resolved = _ResolvedConnection(
        connection_type="ftp",
        properties={"initial_directory": "/uploads"},
    )

    class _UseCase:
        async def execute(self, **_kwargs):
            return resolved

    monkeypatch.setattr(deps_module, "_build_resolve_connection_use_case", lambda: _UseCase())

    dependency = deps_module.get_file_storage_facade(
        connection_id="conn-1",
        user=SimpleNamespace(id="user-1", organization_id="org-1", role="admin"),
    )
    facade = await anext(dependency)
    await dependency.aclose()

    assert isinstance(facade, FileStorageFacade)
    assert resolved.closed is True
