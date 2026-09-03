from collections.abc import AsyncIterator
from functools import lru_cache

from db_connection import AccessDeniedError, ConnectionNotFoundError

from src.db import async_engine
from src.modules.db_connection import build_resolve_connection_client_use_case, ResolvedConnectionClient
from src.modules.file_storage import (
    DefaultStorageGatewayFactory,
    FileStorageFacade,
    FileStorageProvider,
    ResolvedDVTServiceFilesStorageConnection,
    ResolvedFTPStorageConnection,
    ResolvedS3StorageConnection,
    ResolvedSFTPStorageConnection,
)
from src.modules.file_storage.flow.connections import ResolvedStorageConnection, ResolvedSMBStorageConnection
from src.modules.file_storage.flow.exceptions import (
    StorageConnectionNotFoundError,
    StorageOperationError,
    UnsupportedStorageBackendError,
)
from src.modules.file_storage.infra.clients import S3StorageClient
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.modules.user.infra.repositories import SQLAlchemyUserRepository

import config


@lru_cache
def _build_resolve_connection_use_case():
    return build_resolve_connection_client_use_case(
        engine=async_engine,
        fernet_key=config.SECURITY.FERNET_KEY,
        user_repository_factory=SQLAlchemyUserRepository
    )


def _optional_string(mapping: dict[str, object], key: str, default: str) -> str:
    value = mapping.get(key)
    if value is None:
        return default
    if isinstance(value, str):
        return value
    raise StorageOperationError(f"Storage connection field '{key}' must be a string")


def _required_string(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    if isinstance(value, str) and value:
        return value
    raise StorageOperationError(f"Storage connection field '{key}' is required")


def _map_resolved_connection(resolved: ResolvedConnectionClient) -> ResolvedStorageConnection:
    properties = resolved.connection.properties
    if not isinstance(properties, dict):
        raise StorageOperationError("Storage connection properties must be a mapping")

    if resolved.type == "s3":
        return ResolvedS3StorageConnection(
            client=S3StorageClient(client=resolved.client),
            bucket=_required_string(properties, "bucket"),
            prefix=_optional_string(properties, "prefix", ""),
        )
    if resolved.type == "ftp":
        return ResolvedFTPStorageConnection(
            client=resolved.client,
            initial_directory=_optional_string(properties, "initial_directory", "/"),
        )
    if resolved.type == "sftp":
        return ResolvedSFTPStorageConnection(
            client=resolved.client,
            initial_directory=_optional_string(properties, "initial_directory", "/"),
        )
    if resolved.type == "smbprotocol":
        return ResolvedSMBStorageConnection(
            client=resolved.client,
            initial_directory=_optional_string(properties, "initial_directory", "/"),
        )
    if resolved.type == "dvt_service_files":
        return ResolvedDVTServiceFilesStorageConnection(
            client=resolved.client,
            root_prefix=_optional_string(properties, "root_prefix", ""),
        )

    raise UnsupportedStorageBackendError(resolved.type)


async def get_file_storage_facade(
    connection_id: str,
    user: UserAccessOnly,
) -> AsyncIterator[FileStorageFacade]:
    resolved: ResolvedConnectionClient | None = None
    try:
        resolved = await _build_resolve_connection_use_case().execute(
            connection_id=connection_id,
            actor=user,
        )
        storage_connection = _map_resolved_connection(resolved)
        provider = FileStorageProvider(
            connection=storage_connection,
            gateway_factory=DefaultStorageGatewayFactory(),
        )
        yield FileStorageFacade(
            provider,
            presign_expire_seconds=config.OTHER.S3_PRESIGN_EXPIRE_SECONDS,
            max_upload_size_bytes=10 * 1024 * 1024,
        )
    except (AccessDeniedError, ConnectionNotFoundError):
        raise StorageConnectionNotFoundError(connection_id) from None
    finally:
        if resolved is not None:
            await resolved.aclose()
