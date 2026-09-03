from __future__ import annotations

import errno
import mimetypes
import stat
from contextlib import contextmanager
from datetime import datetime, timezone

try:
    from smbprotocol.exceptions import SMBOSError
    from smbprotocol.header import NtStatus
except ImportError:  # pragma: no cover
    SMBOSError = None
    NtStatus = None

from ...domain.entities import (
    DeleteResult,
    DownloadedFile,
    StorageFileNode,
    StorageFolderNode,
    StorageTree,
)
from ...domain.types import StorageBackendKind
from ...domain.value_objects import StorageEntryName, StorageRelativePath
from ...flow.connections import ResolvedSMBStorageConnection
from ...flow.exceptions import StorageOperationError, UnsupportedTransferStrategyError
from ...flow.gateways import FileStorageGateway


class SMBFileStorageGateway(FileStorageGateway):
    _FILE_ATTRIBUTE_DIRECTORY = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
    _SMB_NOT_FOUND_STATUSES = {
        getattr(NtStatus, "STATUS_OBJECT_NAME_NOT_FOUND", None),
        getattr(NtStatus, "STATUS_OBJECT_PATH_NOT_FOUND", None),
        getattr(NtStatus, "STATUS_NOT_FOUND", None),
    }

    def __init__(self, connection: ResolvedSMBStorageConnection) -> None:
        self._connection = connection

    @contextmanager
    def _client(self):
        yield self._connection.client

    def _root_dir(self) -> StorageRelativePath:
        return StorageRelativePath.from_raw(self._connection.initial_directory)

    def _directory_path(self, relative_path: StorageRelativePath) -> str | None:
        parts = [self._root_dir().value]
        if relative_path.value:
            parts.append(relative_path.value)
        clean = "/".join(part for part in parts if part)
        return clean or None

    def _file_location(self, relative_path: StorageRelativePath, name: str | None = None) -> tuple[str | None, str]:
        entry_name = StorageEntryName.from_raw(name).value if name is not None else relative_path.name
        parent_path = relative_path if name is not None else relative_path.parent
        return self._directory_path(parent_path), entry_name

    def _join_client_path(self, parent_path: str | None, child_name: str) -> str:
        if not parent_path:
            return child_name
        return f"{parent_path.rstrip('/')}/{child_name}"

    @classmethod
    def _is_missing_directory_error(cls, exc: Exception) -> bool:
        if isinstance(exc, FileNotFoundError):
            return True

        exc_errno = getattr(exc, "errno", None)
        if exc_errno == errno.ENOENT:
            return True

        if SMBOSError is not None and isinstance(exc, SMBOSError):
            return getattr(exc, "ntstatus", None) in cls._SMB_NOT_FOUND_STATUSES
        return False

    def _ensure_dir(self, client, target_path: str | None) -> None:
        if not target_path:
            return

        current_path = None
        for part in target_path.strip("/").split("/"):
            current_path = self._join_client_path(current_path, part)
            try:
                client.stat(current_path)
            except Exception as exc:  # noqa: BLE001
                if not self._is_missing_directory_error(exc):
                    raise
                client.mkdir(current_path)

    def _rename_relative_path(
        self,
        *,
        source_path: StorageRelativePath,
        destination_path: StorageRelativePath,
    ) -> None:
        if source_path == destination_path:
            return

        source_dir, source_name = self._file_location(source_path)
        destination_dir, destination_name = self._file_location(destination_path)
        with self._client() as client:
            client.rename(
                src_path=source_dir,
                src_filename=source_name,
                dst_path=destination_dir,
                dst_filename=destination_name,
            )

    @staticmethod
    def _entry_name(entry) -> str:
        name = getattr(entry, "name", None) or getattr(entry, "filename", None)
        if not isinstance(name, str) or not name:
            raise StorageOperationError("Failed to inspect SMB directory entry name")
        return name

    @staticmethod
    def _entry_info(entry):
        entry_info = getattr(entry, "smb_info", None) or getattr(entry, "_dir_info", None)
        if entry_info is None:
            raise StorageOperationError("Failed to inspect SMB directory entry metadata")
        return entry_info

    @classmethod
    def _entry_is_dir(cls, entry, entry_info) -> bool:
        is_dir = getattr(entry, "is_dir", None)
        if callable(is_dir):
            return bool(is_dir())
        file_attributes = getattr(entry_info, "file_attributes", None)
        if file_attributes is None:
            return False
        return bool(file_attributes & cls._FILE_ATTRIBUTE_DIRECTORY)

    @staticmethod
    def _entry_permissions(entry_info) -> str | None:
        return getattr(entry_info, "permissions", None)

    @staticmethod
    def _entry_last_modified(entry_info) -> datetime | None:
        entry_mtime = getattr(entry_info, "last_write_time", None)
        if entry_mtime is None:
            return None
        if isinstance(entry_mtime, datetime):
            return entry_mtime.astimezone(timezone.utc)
        return datetime.fromtimestamp(entry_mtime, tz=timezone.utc)

    def list_nodes(self, *, path: str, max_items: int) -> StorageTree:
        relative_path = StorageRelativePath.from_raw(path)
        directory_path = self._directory_path(relative_path)
        try:
            with self._client() as client:
                entries = list(client.scandir(directory_path))
            nodes = []
            for entry in entries[:max_items]:
                name = self._entry_name(entry)
                if name in {".", ".."}:
                    continue

                entry_info = self._entry_info(entry)
                permissions = self._entry_permissions(entry_info)
                child_path = relative_path.join(name).value
                if self._entry_is_dir(entry, entry_info):
                    nodes.append(
                        StorageFolderNode(
                            name=name,
                            path=child_path,
                            permissions=permissions,
                        )
                    )
                    continue

                nodes.append(
                    StorageFileNode(
                        name=name,
                        path=child_path,
                        size=int(getattr(entry_info, "end_of_file", 0)),
                        last_modified=self._entry_last_modified(entry_info),
                        permissions=permissions,
                    )
                )

            return StorageTree(
                backend_kind=StorageBackendKind.SMB,
                path=relative_path.value,
                nodes=nodes,
                is_truncated=len(entries) > max_items,
                next_token=None,
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to list SMB directory: {exc}") from exc

    def create_folder(self, *, path: str, folder_name: str) -> None:
        relative_path = StorageRelativePath.from_raw(path).join(folder_name)
        target_directory = self._directory_path(relative_path)
        try:
            with self._client() as client:
                self._ensure_dir(client, target_directory)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to create SMB directory: {exc}") from exc

    def rename_path(self, *, path: str, new_name: str) -> None:
        try:
            source_path = StorageRelativePath.from_raw(path)
            destination_path = source_path.with_name(new_name)
            self._rename_relative_path(source_path=source_path, destination_path=destination_path)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to rename SMB path: {exc}") from exc

    def move_path(self, *, path: str, target_path: str) -> None:
        try:
            source_path = StorageRelativePath.from_raw(path)
            destination_path = source_path.move_to(target_path)
            self._rename_relative_path(source_path=source_path, destination_path=destination_path)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to move SMB path: {exc}") from exc

    def delete_files(self, *, paths: list[str]) -> DeleteResult:
        deleted = 0
        errors: list[str] = []
        try:
            with self._client() as client:
                for path in paths:
                    try:
                        directory_path, filename = self._file_location(StorageRelativePath.from_raw(path))
                        client.remove(path=directory_path, filename=filename)
                        deleted += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"{path}: {exc}")
            return DeleteResult(deleted_count=deleted, errors=errors)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to delete SMB files: {exc}") from exc

    def _delete_folder_recursive(self, client, directory_path: str | None) -> tuple[int, list[str]]:
        deleted = 0
        errors: list[str] = []

        for entry in client.scandir(directory_path):
            name = self._entry_name(entry)
            if name in {".", ".."}:
                continue

            entry_stat = self._entry_info(entry)
            child_directory_path = self._join_client_path(directory_path, name)
            if self._entry_is_dir(entry, entry_stat):
                child_deleted, child_errors = self._delete_folder_recursive(client, child_directory_path)
                deleted += child_deleted
                errors.extend(child_errors)
                continue

            try:
                client.remove(path=directory_path, filename=name)
                deleted += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{child_directory_path}: {exc}")

        try:
            client.rmdir(directory_path)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{directory_path or '/'}: {exc}")
        return deleted, errors

    def delete_folder(self, *, path: str) -> DeleteResult:
        relative_path = StorageRelativePath.from_raw(path)
        directory_path = self._directory_path(relative_path)
        try:
            with self._client() as client:
                deleted, errors = self._delete_folder_recursive(client, directory_path)
            return DeleteResult(deleted_count=deleted, errors=errors)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to delete SMB directory: {exc}") from exc

    def generate_upload_presign(self, **kwargs):
        raise UnsupportedTransferStrategyError(StorageBackendKind.SMB.value, "Presigned upload")

    def generate_download_presign(self, **kwargs):
        raise UnsupportedTransferStrategyError(StorageBackendKind.SMB.value, "Presigned download")

    def upload_file(
        self,
        *,
        path: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        relative_path = StorageRelativePath.from_raw(path)
        directory_path = self._directory_path(relative_path)
        try:
            with self._client() as client:
                self._ensure_dir(client, directory_path)
                with client.open_file(path=directory_path, filename=filename, mode="wb") as fp:
                    fp.write(content)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to upload SMB file: {exc}") from exc

    def download_file(self, *, path: str, filename: str) -> DownloadedFile:
        relative_path = StorageRelativePath.from_raw(path)
        directory_path = self._directory_path(relative_path)
        try:
            with self._client() as client:
                with client.open_file(path=directory_path, filename=filename, mode="rb") as fp:
                    content = fp.read()
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to download SMB file: {exc}") from exc

        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return DownloadedFile(
            filename=StorageEntryName.from_raw(filename).value,
            content=content,
            media_type=media_type,
        )
