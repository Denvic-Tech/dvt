from __future__ import annotations

import io
import mimetypes
from contextlib import contextmanager
from datetime import datetime, timezone
from ftplib import error_perm
from posixpath import basename

from ...domain.entities import (
    DeleteResult,
    DownloadedFile,
    StorageFileNode,
    StorageFolderNode,
    StorageTree,
)
from ...domain.types import StorageBackendKind
from ...domain.value_objects import StorageEntryName, StorageRelativePath
from ...flow.connections import ResolvedFTPStorageConnection
from ...flow.exceptions import StorageOperationError, UnsupportedTransferStrategyError


class FTPFileStorageGateway:
    def __init__(self, connection: ResolvedFTPStorageConnection) -> None:
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

    def _relative_child_path(self, parent: StorageRelativePath, child_name: str) -> str:
        return parent.join(child_name).value

    def _directory_exists(self, client, path: str) -> bool:
        original_cwd = client.pwd()
        try:
            client.cwd(path)
        except Exception:  # noqa: BLE001
            return False
        finally:
            try:
                client.cwd(original_cwd)
            except Exception:  # noqa: BLE001
                pass
        return True

    def _ensure_dir(self, client, target_path: str) -> None:
        if target_path in {"", "/"}:
            return
        current = ""
        for part in target_path.strip("/").split("/"):
            current = f"{current}/{part}" if current else f"/{part}"
            try:
                client.cwd(current)
            except error_perm as cwd_exc:
                try:
                    client.mkd(current)
                except error_perm as mkd_exc:
                    if not self._directory_exists(client, current):
                        raise mkd_exc from cwd_exc

    def _rename_absolute_path(self, *, source_path: StorageRelativePath, destination_path: StorageRelativePath) -> None:
        if source_path == destination_path:
            return

        absolute_source_path = self._absolute_path(source_path)
        absolute_destination_path = self._absolute_path(destination_path)
        with self._client() as client:
            client.rename(absolute_source_path, absolute_destination_path)

    @staticmethod
    def _is_unsupported_mlsd(exc: Exception) -> bool:
        return isinstance(exc, error_perm) and "unknown command" in str(exc).lower()

    def _infer_entry_type(self, client, absolute_path: str) -> str:
        original_cwd = client.pwd()
        try:
            client.cwd(absolute_path)
        except Exception:  # noqa: BLE001
            return "file"
        finally:
            try:
                client.cwd(original_cwd)
            except Exception:  # noqa: BLE001
                pass
        return "dir"

    def _collect_entry_facts_fallback(self, client, absolute_path: str) -> dict[str, str]:
        entry_type = self._infer_entry_type(client, absolute_path)
        facts: dict[str, str] = {"type": entry_type}
        if entry_type == "file":
            try:
                size = client.size(absolute_path)
            except Exception:  # noqa: BLE001
                size = None
            if size is not None:
                facts["size"] = str(size)

            try:
                modify = client.sendcmd(f"MDTM {absolute_path}")
            except Exception:  # noqa: BLE001
                modify = None
            if modify and modify.startswith("213 "):
                facts["modify"] = modify[4:].strip()
        return facts

    def _list_entries(self, client, absolute_path: str) -> list[tuple[str, dict[str, str]]]:
        try:
            return list(client.mlsd(absolute_path))
        except Exception as exc:  # noqa: BLE001
            if not self._is_unsupported_mlsd(exc):
                raise

        raw_entries = client.nlst(absolute_path)
        entries: list[tuple[str, dict[str, str]]] = []
        current_path = absolute_path.rstrip("/")
        for raw_entry in raw_entries:
            normalized_entry = raw_entry.rstrip("/")
            if normalized_entry in {"", current_path}:
                continue

            name = basename(normalized_entry)
            if name in {".", ".."}:
                continue

            entry_path = normalized_entry if normalized_entry.startswith("/") else f"{current_path}/{normalized_entry}"
            entries.append((name, self._collect_entry_facts_fallback(client, entry_path)))
        return entries

    def list_nodes(self, *, path: str, max_items: int) -> StorageTree:
        relative_path = StorageRelativePath.from_raw(path)
        absolute_path = self._absolute_path(relative_path)
        try:
            with self._client() as client:
                entries = self._list_entries(client, absolute_path)
            nodes = []
            for name, facts in entries[:max_items]:
                if name in {".", ".."}:
                    continue
                relative_child_path = self._relative_child_path(relative_path, name)
                permissions = facts.get("unix.mode") or facts.get("perm")
                if facts.get("type") == "dir":
                    nodes.append(
                        StorageFolderNode(
                            name=name,
                            path=relative_child_path,
                            permissions=permissions,
                        )
                    )
                    continue

                last_modified = None
                modify_value = facts.get("modify")
                if modify_value:
                    try:
                        last_modified = datetime.strptime(modify_value, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                    except ValueError:
                        last_modified = None

                nodes.append(
                    StorageFileNode(
                        name=name,
                        path=relative_child_path,
                        size=int(facts.get("size", 0)),
                        last_modified=last_modified,
                        permissions=permissions,
                    )
                )

            return StorageTree(
                backend_kind=StorageBackendKind.FTP,
                path=relative_path.value,
                nodes=nodes,
                is_truncated=len(entries) > max_items,
                next_token=None,
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to list FTP directory: {exc}") from exc

    def create_folder(self, *, path: str, folder_name: str) -> None:
        relative_path = StorageRelativePath.from_raw(path)
        target_dir = self._absolute_path(relative_path, folder_name)
        try:
            with self._client() as client:
                self._ensure_dir(client, target_dir)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to create FTP directory: {exc}") from exc

    def rename_path(self, *, path: str, new_name: str) -> None:
        try:
            source_path = StorageRelativePath.from_raw(path)
            destination_path = source_path.with_name(new_name)
            self._rename_absolute_path(source_path=source_path, destination_path=destination_path)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to rename FTP path: {exc}") from exc

    def move_path(self, *, path: str, target_path: str) -> None:
        try:
            source_path = StorageRelativePath.from_raw(path)
            destination_path = source_path.move_to(target_path)
            self._rename_absolute_path(source_path=source_path, destination_path=destination_path)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to move FTP path: {exc}") from exc

    def delete_files(self, *, paths: list[str]) -> DeleteResult:
        deleted = 0
        errors: list[str] = []
        try:
            with self._client() as client:
                for path in paths:
                    try:
                        absolute_path = self._absolute_path(StorageRelativePath.from_raw(path))
                        client.delete(absolute_path)
                        deleted += 1
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"{path}: {exc}")
            return DeleteResult(deleted_count=deleted, errors=errors)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to delete FTP files: {exc}") from exc

    def _delete_folder_recursive(self, client, absolute_path: str) -> tuple[int, list[str]]:
        deleted = 0
        errors: list[str] = []
        for name, facts in self._list_entries(client, absolute_path):
            if name in {".", ".."}:
                continue
            child_path = f"{absolute_path.rstrip('/')}/{name}"
            if facts.get("type") == "dir":
                child_deleted, child_errors = self._delete_folder_recursive(client, child_path)
                deleted += child_deleted
                errors.extend(child_errors)
            else:
                try:
                    client.delete(child_path)
                    deleted += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{child_path}: {exc}")
        try:
            client.rmd(absolute_path)
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
            raise StorageOperationError(f"Failed to delete FTP directory: {exc}") from exc

    def generate_upload_presign(self, **kwargs):
        raise UnsupportedTransferStrategyError(StorageBackendKind.FTP.value, "Presigned upload")

    def generate_download_presign(self, **kwargs):
        raise UnsupportedTransferStrategyError(StorageBackendKind.FTP.value, "Presigned download")

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
                payload = io.BytesIO(content)
                client.storbinary(f"STOR {absolute_path}", payload)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to upload FTP file: {exc}") from exc

    def download_file(self, *, path: str, filename: str) -> DownloadedFile:
        relative_path = StorageRelativePath.from_raw(path)
        absolute_path = self._absolute_path(relative_path, filename)
        buffer = io.BytesIO()
        try:
            with self._client() as client:
                client.retrbinary(f"RETR {absolute_path}", buffer.write)
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to download FTP file: {exc}") from exc

        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        return DownloadedFile(
            filename=StorageEntryName.from_raw(filename).value,
            content=buffer.getvalue(),
            media_type=media_type,
        )
