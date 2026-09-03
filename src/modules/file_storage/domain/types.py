from enum import StrEnum


class StorageBackendKind(StrEnum):
    S3 = "s3"
    FTP = "ftp"
    SFTP = "sftp"
    SMB = "smb"
    DVT_SERVICE_FILES = "dvt_service_files"
