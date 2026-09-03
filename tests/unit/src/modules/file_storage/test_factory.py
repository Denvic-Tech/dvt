from src.modules.file_storage.flow.connections import (
    ResolvedDVTServiceFilesStorageConnection,
    ResolvedFTPStorageConnection,
    ResolvedSMBStorageConnection,
    ResolvedS3StorageConnection,
    ResolvedSFTPStorageConnection,
)
from src.modules.file_storage.infra.clients import S3StorageClient
from src.modules.file_storage.infra.gateways.file_storage import DefaultStorageGatewayFactory
from src.modules.file_storage.infra.gateways.dvt_service_files import DVTServiceFilesStorageGateway
from src.modules.file_storage.infra.gateways.ftp import FTPFileStorageGateway
from src.modules.file_storage.infra.gateways.s3 import S3FileStorageGateway
from src.modules.file_storage.infra.gateways.smb import SMBFileStorageGateway
from src.modules.file_storage.infra.gateways.sftp import SFTPFileStorageGateway


def test_default_storage_gateway_factory_dispatches_by_resolved_connection_type() -> None:
    factory = DefaultStorageGatewayFactory()

    s3_gateway = factory.build(
        ResolvedS3StorageConnection(
            client=S3StorageClient(client=object()),
            bucket="bucket",
            prefix="incoming",
        )
    )
    ftp_gateway = factory.build(
        ResolvedFTPStorageConnection(
            client=object(),
            initial_directory="/uploads",
        )
    )
    sftp_gateway = factory.build(
        ResolvedSFTPStorageConnection(
            client=object(),
            initial_directory="/uploads",
        )
    )
    smb_gateway = factory.build(
        ResolvedSMBStorageConnection(
            client=object(),
            initial_directory="/uploads",
        )
    )
    dvt_service_files_gateway = factory.build(
        ResolvedDVTServiceFilesStorageConnection(
            client=object(),
            root_prefix="node-inputs/node-1/file",
        )
    )

    assert isinstance(s3_gateway, S3FileStorageGateway)
    assert isinstance(ftp_gateway, FTPFileStorageGateway)
    assert isinstance(sftp_gateway, SFTPFileStorageGateway)
    assert isinstance(smb_gateway, SMBFileStorageGateway)
    assert isinstance(dvt_service_files_gateway, DVTServiceFilesStorageGateway)
