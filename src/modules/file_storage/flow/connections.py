from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ResolvedS3StorageConnection:
    client: Any
    bucket: str
    prefix: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedFTPStorageConnection:
    client: Any
    initial_directory: str = "/"


@dataclass(frozen=True, slots=True)
class ResolvedSFTPStorageConnection:
    client: Any
    initial_directory: str = "/"


@dataclass(frozen=True, slots=True)
class ResolvedSMBStorageConnection:
    client: Any
    initial_directory: str = "/"


@dataclass(frozen=True, slots=True)
class ResolvedDVTServiceFilesStorageConnection:
    client: Any
    root_prefix: str = ""


ResolvedStorageConnection = (
    ResolvedS3StorageConnection
    | ResolvedFTPStorageConnection
    | ResolvedSFTPStorageConnection
    | ResolvedSMBStorageConnection
    | ResolvedDVTServiceFilesStorageConnection
)
