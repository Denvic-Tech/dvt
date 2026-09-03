class FileStorageFlowError(Exception):
    """Base flow error for file storage."""


class StorageConnectionNotFoundError(FileStorageFlowError):
    def __init__(self, connection_id: str) -> None:
        super().__init__(f"Storage connection '{connection_id}' not found")


class UnsupportedStorageBackendError(FileStorageFlowError):
    def __init__(self, backend_type: str) -> None:
        super().__init__(f"Unsupported storage backend: {backend_type}")


class UnsupportedTransferStrategyError(FileStorageFlowError):
    def __init__(self, backend_type: str, operation: str) -> None:
        super().__init__(f"{operation} is not supported for storage backend '{backend_type}'")


class StorageOperationError(FileStorageFlowError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


class FileTooLargeError(FileStorageFlowError):
    def __init__(self, max_size_bytes: int) -> None:
        super().__init__(f"File exceeds maximum allowed size of {max_size_bytes} bytes")
