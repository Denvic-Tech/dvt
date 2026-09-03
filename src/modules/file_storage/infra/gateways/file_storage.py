from __future__ import annotations

from ...flow.connections import (
    ResolvedDVTServiceFilesStorageConnection,
    ResolvedFTPStorageConnection,
    ResolvedS3StorageConnection,
    ResolvedSFTPStorageConnection,
    ResolvedSMBStorageConnection,
    ResolvedStorageConnection,
)
from ...flow.exceptions import UnsupportedStorageBackendError
from ...flow.gateways import FileStorageGateway, StorageGatewayFactory
from .ftp import FTPFileStorageGateway
from .dvt_service_files import DVTServiceFilesStorageGateway
from .s3 import S3FileStorageGateway
from .sftp import SFTPFileStorageGateway
from .smb import SMBFileStorageGateway


class DefaultStorageGatewayFactory(StorageGatewayFactory):
    def build(self, connection: ResolvedStorageConnection) -> FileStorageGateway:
        if isinstance(connection, ResolvedDVTServiceFilesStorageConnection):
            return DVTServiceFilesStorageGateway(connection)
        if isinstance(connection, ResolvedS3StorageConnection):
            return S3FileStorageGateway(connection)
        if isinstance(connection, ResolvedFTPStorageConnection):
            return FTPFileStorageGateway(connection)
        if isinstance(connection, ResolvedSFTPStorageConnection):
            return SFTPFileStorageGateway(connection)
        if isinstance(connection, ResolvedSMBStorageConnection):
            return SMBFileStorageGateway(connection)
        raise UnsupportedStorageBackendError(type(connection).__name__)
