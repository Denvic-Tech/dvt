from src.db import engine
from src.modules.db_connection.infra.connectors.dvt_service_files import DVTServiceFilesClient
from src.modules.file_storage import (
    DefaultStorageGatewayFactory,
    FileStorageFacade,
    FileStorageProvider,
    ResolvedDVTServiceFilesStorageConnection,
)

import config


def _root_prefix(node_id: str, input_name: str) -> str:
    from src.modules.file_storage.domain.value_objects import StorageEntryName

    safe_node_id = StorageEntryName.from_raw(node_id).value
    safe_input_name = StorageEntryName.from_raw(input_name).value
    return f"node-inputs/{safe_node_id}/{safe_input_name}"


def build_dvt_service_files_storage(
    *,
    organization_id: str,
    project_id: str,
    node_id: str,
    input_name: str,
) -> FileStorageFacade:
    client = DVTServiceFilesClient(
        engine=engine,
        organization_id=organization_id,
        project_id=project_id,
        root_prefix=_root_prefix(node_id, input_name),
    )
    provider = FileStorageProvider(
        connection=ResolvedDVTServiceFilesStorageConnection(client=client),
        gateway_factory=DefaultStorageGatewayFactory(),
    )
    return FileStorageFacade(
        provider,
        presign_expire_seconds=config.OTHER.S3_PRESIGN_EXPIRE_SECONDS,
        max_upload_size_bytes=config.OTHER.NODE_FILE_UPLOAD_MAX_SIZE_BYTES,
    )
