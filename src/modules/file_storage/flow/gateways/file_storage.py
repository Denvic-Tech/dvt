from __future__ import annotations

from typing import Protocol

from ...domain.entities import DeleteResult, DownloadedFile, PresignedUpload, StorageTree
from ..connections import ResolvedStorageConnection


class FileStorageGateway(Protocol):
    def list_nodes(self, *, path: str, max_items: int) -> StorageTree: ...

    def create_folder(self, *, path: str, folder_name: str) -> None: ...

    def rename_path(self, *, path: str, new_name: str) -> None: ...

    def move_path(self, *, path: str, target_path: str) -> None: ...

    def delete_files(self, *, paths: list[str]) -> DeleteResult: ...

    def delete_folder(self, *, path: str) -> DeleteResult: ...

    def generate_upload_presign(
        self,
        *,
        path: str,
        filename: str,
        content_type_prefix: str,
        expires_seconds: int,
        max_upload_size_bytes: int,
    ) -> PresignedUpload: ...

    def generate_download_presign(
        self,
        *,
        path: str,
        filename: str,
        expires_seconds: int,
    ) -> str: ...

    def upload_file(
        self,
        *,
        path: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None: ...

    def download_file(self, *, path: str, filename: str) -> DownloadedFile: ...


class StorageGatewayFactory(Protocol):
    def build(self, connection: ResolvedStorageConnection) -> FileStorageGateway: ...
