from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .types import StorageBackendKind


@dataclass(frozen=True, slots=True)
class StorageFileNode:
    name: str
    path: str
    size: int
    last_modified: datetime | None = None
    etag: str | None = None
    storage_class: str | None = None
    permissions: str | None = None


@dataclass(frozen=True, slots=True)
class StorageFolderNode:
    name: str
    path: str
    permissions: str | None = None


StorageNode = StorageFileNode | StorageFolderNode


@dataclass(frozen=True, slots=True)
class StorageTree:
    backend_kind: StorageBackendKind
    path: str
    nodes: list[StorageNode]
    is_truncated: bool
    next_token: str | None = None


@dataclass(frozen=True, slots=True)
class DeleteResult:
    deleted_count: int
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    url: str
    fields: dict[str, str]


@dataclass(frozen=True, slots=True)
class DownloadedFile:
    filename: str
    content: bytes
    media_type: str | None = None
