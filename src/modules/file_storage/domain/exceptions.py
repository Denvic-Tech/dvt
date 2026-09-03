class FileStorageDomainError(Exception):
    """Base domain error for file storage."""


class InvalidStoragePathError(FileStorageDomainError):
    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"Invalid storage path '{path}': {reason}")


class InvalidStorageEntryNameError(FileStorageDomainError):
    def __init__(self, name: str, reason: str) -> None:
        super().__init__(f"Invalid storage entry name '{name}': {reason}")
