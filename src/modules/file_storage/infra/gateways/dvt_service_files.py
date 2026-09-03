from __future__ import annotations

import mimetypes

from ...domain.entities import (
    DeleteResult,
    DownloadedFile,
    StorageFileNode,
    StorageFolderNode,
    StorageTree,
)
from ...domain.types import StorageBackendKind
from ...domain.value_objects import StorageEntryName, StorageRelativePath
from ...flow.connections import ResolvedDVTServiceFilesStorageConnection
from ...flow.exceptions import StorageOperationError, UnsupportedTransferStrategyError
from ...flow.gateways import FileStorageGateway


class DVTServiceFilesStorageGateway(FileStorageGateway):
    def __init__(self, connection: ResolvedDVTServiceFilesStorageConnection) -> None:
        self._connection = connection

    @property
    def _client(self):
        return self._connection.client

    def list_nodes(self, *, path: str, max_items: int) -> StorageTree:
        relative_path = StorageRelativePath.from_raw(path)
        try:
            entries = self._client.list_entries(relative_path.value)
            nodes = []
            for entry in entries[:max_items]:
                if entry.is_dir:
                    nodes.append(StorageFolderNode(name=entry.name, path=entry.path))
                    continue
                nodes.append(
                    StorageFileNode(
                        name=entry.name,
                        path=entry.path,
                        size=entry.size,
                        last_modified=entry.updated_at,
                        etag=entry.sha256,
                    )
                )
            return StorageTree(
                backend_kind=StorageBackendKind.DVT_SERVICE_FILES,
                path=relative_path.value,
                nodes=nodes,
                is_truncated=len(entries) > max_items,
                next_token=None,
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to list DVT service files: {exc}") from exc

    def create_folder(self, *, path: str, folder_name: str) -> None:
        try:
            relative_path = StorageRelativePath.from_raw(path).join(folder_name)
            self._client.mkdir(relative_path.value)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to create DVT service files folder: {exc}") from exc

    def rename_path(self, *, path: str, new_name: str) -> None:
        try:
            source_path = StorageRelativePath.from_raw(path)
            destination_path = source_path.with_name(new_name)
            self._client.rename(src_path=source_path.value, dst_path=destination_path.value)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to rename DVT service file path: {exc}") from exc

    def move_path(self, *, path: str, target_path: str) -> None:
        try:
            source_path = StorageRelativePath.from_raw(path)
            destination_path = source_path.move_to(target_path)
            self._client.rename(src_path=source_path.value, dst_path=destination_path.value)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to move DVT service file path: {exc}") from exc

    def delete_files(self, *, paths: list[str]) -> DeleteResult:
        deleted = 0
        errors: list[str] = []
        for path in paths:
            try:
                self._client.remove(StorageRelativePath.from_raw(path).value)
                deleted += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path}: {exc}")
        return DeleteResult(deleted_count=deleted, errors=errors)

    def delete_folder(self, *, path: str) -> DeleteResult:
        try:
            entries = self._client.list_entries(StorageRelativePath.from_raw(path).value)
            deleted = 0
            errors: list[str] = []
            for entry in entries:
                if entry.is_dir:
                    result = self.delete_folder(path=entry.path)
                    deleted += result.deleted_count
                    errors.extend(result.errors)
                else:
                    result = self.delete_files(paths=[entry.path])
                    deleted += result.deleted_count
                    errors.extend(result.errors)
            try:
                self._client.rmdir(StorageRelativePath.from_raw(path).value)
            except FileNotFoundError:
                pass
            return DeleteResult(deleted_count=deleted, errors=errors)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to delete DVT service files folder: {exc}") from exc

    def generate_upload_presign(self, **kwargs):
        raise UnsupportedTransferStrategyError(
            StorageBackendKind.DVT_SERVICE_FILES.value,
            "Presigned upload",
        )

    def generate_download_presign(self, **kwargs):
        raise UnsupportedTransferStrategyError(
            StorageBackendKind.DVT_SERVICE_FILES.value,
            "Presigned download",
        )

    def upload_file(
        self,
        *,
        path: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        try:
            relative_path = StorageRelativePath.from_raw(path)
            entry_name = StorageEntryName.from_raw(filename)
            self._client.upload_file(
                path=relative_path.value,
                filename=entry_name.value,
                content=content,
                content_type=content_type,
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to upload DVT service file: {exc}") from exc

    def download_file(self, *, path: str, filename: str) -> DownloadedFile:
        try:
            relative_path = StorageRelativePath.from_raw(path)
            entry_name = StorageEntryName.from_raw(filename)
            name, content, media_type = self._client.download_file(
                path=relative_path.value,
                filename=entry_name.value,
            )
            return DownloadedFile(
                filename=name,
                content=content,
                media_type=media_type or mimetypes.guess_type(name)[0] or "application/octet-stream",
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to download DVT service file: {exc}") from exc
