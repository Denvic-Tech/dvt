from __future__ import annotations

import io
import mimetypes
import stat
from contextlib import contextmanager
from datetime import datetime, timezone

from ...domain.entities import (
    DeleteResult,
    DownloadedFile,
    StorageFileNode,
    StorageFolderNode,
    StorageTree,
)
from ...domain.types import StorageBackendKind
from ...domain.value_objects import StorageEntryName, StorageRelativePath
from ...flow.connections import ResolvedSFTPStorageConnection
from ...flow.exceptions import StorageOperationError, UnsupportedTransferStrategyError


class SFTPFileStorageGateway:
    def __init__(self, connection: ResolvedSFTPStorageConnection) -> None:
        self._connection = connection

    @contextmanager
    def _client(self):
        yield self._connection.client

    def _root_dir(self) -> str:
        root = (self._connection.initial_directory or "/").replace("\\", "/").strip("/")
        return f"/{root}" if root else "/"

    def _absolute_path(self, relative_path: StorageRelativePath, name: str | None = None) -> str:
        parts = [self._root_dir().strip("/")]
        if relative_path.value:
            parts.append(relative_path.value)
        if name:
            parts.append(StorageEntryName.from_raw(name).value)
        clean = "/".join(part for part in parts if part)
        return f"/{clean}" if clean else "/"

    def _ensure_dir(self, client, target_path: str) -> None:
        if target_path in {"", "/"}:
            return
        current = ""
        for part in target_path.strip("/").split("/"):
            current = f"{current}/{part}" if current else f"/{part}"
            try:
                client.stat(current)
            except OSError:
                client.mkdir(current)

    def _rename_absolute_path(self, *, source_path: StorageRelativePath, destination_path: StorageRelativePath) -> None:
        if source_path == destination_path:
            return

        absolute_source_path = self._absolute_path(source_path)
        absolute_destination_path = self._absolute_path(destination_path)
        with self._client() as client:
            client.rename(absolute_source_path, absolute_destination_path)

    def list_nodes(self, *, path: str, max_items: int) -> StorageTree:
        relative_path = StorageRelativePath.from_raw(path)
        absolute_path = self._absolute_path(relative_path)
        try:
            with self._client() as client:
                entries = list(client.listdir_attr(absolute_path))
            nodes = []
            for entry in entries[:max_items]:
                relative_child_path = relative_path.join(entry.filename).value
                permissions = oct(entry.st_mode & 0o777)
                if stat.S_ISDIR(entry.st_mode):
                    nodes.append(
                        StorageFolderNode(
                            name=entry.filename,
                            path=relative_child_path,
                            permissions=permissions,
                        )
                    )
                    continue
                last_modified = datetime.fromtimestamp(entry.st_mtime, tz=timezone.utc)
                nodes.append(
                    StorageFileNode(
                        name=entry.filename,
                        path=relative_child_path,
                        size=int(entry.st_size),
                        last_modified=last_modified,
                        permissions=permissions,
                    )
                )
            return StorageTree(
                backend_kind=StorageBackendKind.SFTP,
                path=relative_path.value,
                nodes=nodes,
                is_truncated=len(entries) > max_items,
                next_token=None,
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to list SFTP directory: {exc}") from exc

    def create_folder(self, *, path: str, folder_name: str) -> None:
        relative_path = StorageRelativePath.from_raw(path)
        target_dir = self._absolute_path(relative_path, folder_name)
        try:
            with self._client() as client:
                self._ensure_dir(client, target_dir)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to create SFTP directory: {exc}") from exc

    def rename_path(self, *, path: str, new_name: str) -> None:
        try:
            source_path = StorageRelativePath.from_raw(path)
            destination_path = source_path.with_name(new_name)
            self._rename_absolute_path(source_path=source_path, destination_path=destination_path)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to rename SFTP path: {exc}") from exc

    def move_path(self, *, path: str, target_path: str) -> None:
        try:
            source_path = StorageRelativePath.from_raw(path)
            destination_path = source_path.move_to(target_path)
            self._rename_absolute_path(source_path=source_path, destination_path=destination_path)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to move SFTP path: {exc}") from exc

    def delete_files(self, *, paths: list[str]) -> DeleteResult:
        deleted = 0
        errors: list[str] = []
        try:
            with self._client() as client:
                for path in paths:
                    absolute_path = self._absolute_path(StorageRelativePath.from_raw(path))
                    try:
                        client.remove(absolute_path)
                        deleted += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"{path}: {exc}")
            return DeleteResult(deleted_count=deleted, errors=errors)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to delete SFTP files: {exc}") from exc

    def _delete_folder_recursive(self, client, absolute_path: str) -> tuple[int, list[str]]:
        deleted = 0
        errors: list[str] = []
        for entry in client.listdir_attr(absolute_path):
            child_path = f"{absolute_path.rstrip('/')}/{entry.filename}"
            if stat.S_ISDIR(entry.st_mode):
                child_deleted, child_errors = self._delete_folder_recursive(client, child_path)
                deleted += child_deleted
                errors.extend(child_errors)
            else:
                try:
                    client.remove(child_path)
                    deleted += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{child_path}: {exc}")
        try:
            client.rmdir(absolute_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{absolute_path}: {exc}")
        return deleted, errors

    def delete_folder(self, *, path: str) -> DeleteResult:
        relative_path = StorageRelativePath.from_raw(path)
        absolute_path = self._absolute_path(relative_path)
        try:
            with self._client() as client:
                deleted, errors = self._delete_folder_recursive(client, absolute_path)
            return DeleteResult(deleted_count=deleted, errors=errors)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to delete SFTP directory: {exc}") from exc

    def generate_upload_presign(self, **kwargs):
        raise UnsupportedTransferStrategyError(StorageBackendKind.SFTP.value, "Presigned upload")

    def generate_download_presign(self, **kwargs):
        raise UnsupportedTransferStrategyError(StorageBackendKind.SFTP.value, "Presigned download")

    def upload_file(
        self,
        *,
        path: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        relative_path = StorageRelativePath.from_raw(path)
        absolute_dir = self._absolute_path(relative_path)
        absolute_path = self._absolute_path(relative_path, filename)
        try:
            with self._client() as client:
                self._ensure_dir(client, absolute_dir)
                with client.open(absolute_path, "wb") as fp:
                    fp.write(content)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to upload SFTP file: {exc}") from exc

    def download_file(self, *, path: str, filename: str) -> DownloadedFile:
        relative_path = StorageRelativePath.from_raw(path)
        absolute_path = self._absolute_path(relative_path, filename)
        buffer = io.BytesIO()
        try:
            with self._client() as client:
                with client.open(absolute_path, "rb") as fp:
                    buffer.write(fp.read())
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to download SFTP file: {exc}") from exc

        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return DownloadedFile(
            filename=StorageEntryName.from_raw(filename).value,
            content=buffer.getvalue(),
            media_type=media_type,
        )
