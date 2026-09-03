from fastapi import HTTPException

from src.exception_registry.errors_list.gateway import storage as storage_exc
from src.modules.file_storage.domain.exceptions import (
    InvalidStorageEntryNameError,
    InvalidStoragePathError,
)
from src.modules.file_storage.flow.exceptions import (
    FileStorageFlowError,
    FileTooLargeError,
    StorageConnectionNotFoundError,
    StorageOperationError,
    UnsupportedStorageBackendError,
    UnsupportedTransferStrategyError,
)


def to_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, StorageConnectionNotFoundError):
        return storage_exc.ConnectionNotFound(status_code=403, detail=str(exc))
    if isinstance(exc, (InvalidStoragePathError, InvalidStorageEntryNameError, FileTooLargeError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, (UnsupportedTransferStrategyError, UnsupportedStorageBackendError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, StorageOperationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, FileStorageFlowError):
        return HTTPException(status_code=500, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))
