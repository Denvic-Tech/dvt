from __future__ import annotations

import mimetypes

try:
    from botocore.exceptions import ClientError
except ImportError:
    class ClientError(Exception):
        pass

from src import exceptions as src_exc

from ...domain.entities import (
    DeleteResult,
    DownloadedFile,
    PresignedUpload,
    StorageFileNode,
    StorageFolderNode,
    StorageTree,
)
from ...domain.types import StorageBackendKind
from ...domain.value_objects import StorageEntryName, StorageRelativePath
from ...flow.connections import ResolvedS3StorageConnection
from ...flow.exceptions import StorageOperationError


class S3FileStorageGateway:
    def __init__(self, connection: ResolvedS3StorageConnection) -> None:
        self._connection = connection
        self._manager = connection.client

    @property
    def _bucket(self) -> str:
        return self._connection.bucket

    @property
    def _base_prefix(self) -> str:
        return self._connection.prefix.strip("/")

    def _build_key(
        self,
        *,
        path: str | None = None,
        filename: str | None = None,
        trailing_slash_for_folder: bool = False,
    ) -> str:
        relative_path = StorageRelativePath.from_raw(path)
        parts = [self._base_prefix]
        if relative_path.value:
            parts.append(relative_path.value)
        if filename:
            parts.append(StorageEntryName.from_raw(filename).value)

        key = "/".join(parts)
        if trailing_slash_for_folder and key and not key.endswith("/"):
            key += "/"
        return key

    def _move_single_object(self, *, source_key: str, destination_key: str) -> None:
        self._manager.copy_object(
            bucket=self._bucket,
            source_key=source_key,
            destination_key=destination_key,
        )
        self._manager.delete_object(bucket=self._bucket, key=source_key)

    def _move_prefix(self, *, source_prefix: str, destination_prefix: str) -> None:
        keys = self._manager.list_keys(bucket=self._bucket, prefix=source_prefix)
        if not keys:
            raise StorageOperationError("Source path does not exist")

        for source_key in keys:
            suffix = source_key.removeprefix(source_prefix)
            destination_key = f"{destination_prefix}{suffix}"
            self._move_single_object(source_key=source_key, destination_key=destination_key)

    def _path_exists(self, key: str) -> bool:
        try:
            self._manager.head_object(bucket=self._bucket, key=key)
            return True
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code")
            if error_code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def _is_folder_path(self, relative_path: StorageRelativePath) -> bool:
        prefix = self._build_key(path=relative_path.value, trailing_slash_for_folder=True)
        return bool(self._manager.list_keys(bucket=self._bucket, prefix=prefix, max_keys=1))

    def _move_between_paths(
        self,
        *,
        source_path: StorageRelativePath,
        destination_path: StorageRelativePath,
    ) -> None:
        if source_path == destination_path:
            return

        source_key = self._build_key(path=source_path.value)
        destination_key = self._build_key(path=destination_path.value)

        if self._path_exists(source_key):
            self._move_single_object(source_key=source_key, destination_key=destination_key)
            return

        if self._is_folder_path(source_path):
            self._move_prefix(
                source_prefix=self._build_key(path=source_path.value, trailing_slash_for_folder=True),
                destination_prefix=self._build_key(
                    path=destination_path.value,
                    trailing_slash_for_folder=True,
                ),
            )
            return

        raise StorageOperationError("Source path does not exist")

    def list_nodes(self, *, path: str, max_items: int) -> StorageTree:
        try:
            relative_path = StorageRelativePath.from_raw(path)
            full_prefix = self._build_key(path=relative_path.value, trailing_slash_for_folder=True)
            list_params = {
                "Bucket": self._bucket,
                "Delimiter": "/",
                "MaxKeys": max_items,
            }
            if full_prefix:
                list_params["Prefix"] = full_prefix

            response = self._manager.client.list_objects_v2(**list_params)
            mapped_nodes = []
            for prefix_info in response.get("CommonPrefixes", []):
                prefix_key = prefix_info["Prefix"]
                relative_key = self._strip_base_prefix(prefix_key).rstrip("/")
                name = relative_key.rsplit("/", 1)[-1] if relative_key else ""
                if name:
                    mapped_nodes.append(StorageFolderNode(name=name, path=relative_key))

            for obj in response.get("Contents", []):
                key = obj["Key"]
                if key.endswith("/"):
                    continue

                relative_key = self._strip_base_prefix(key)
                name = relative_key.rsplit("/", 1)[-1] if relative_key else ""
                if not name:
                    continue

                mapped_nodes.append(
                    StorageFileNode(
                        name=name,
                        path=relative_key,
                        size=obj["Size"],
                        last_modified=obj.get("LastModified"),
                        etag=obj.get("ETag"),
                        storage_class=obj.get("StorageClass"),
                    )
                )
            return StorageTree(
                backend_kind=StorageBackendKind.S3,
                path=relative_path.value,
                nodes=mapped_nodes,
                is_truncated=response.get("IsTruncated", False),
                next_token=response.get("NextContinuationToken"),
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageOperationError(f"Failed to list S3 objects: {exc}") from exc

    def _strip_base_prefix(self, key: str) -> str:
        if not self._base_prefix:
            return key
        base_with_slash = f"{self._base_prefix}/"
        if key.startswith(base_with_slash):
            return key[len(base_with_slash):]
        return key

    def create_folder(self, *, path: str, folder_name: str) -> None:
        try:
            key = self._build_key(path=path, filename=folder_name, trailing_slash_for_folder=True)
            self._manager.create_folder(bucket=self._bucket, key=key)
        except (ClientError, src_exc.S3ConfigurationError) as exc:
            raise StorageOperationError(f"Failed to create S3 folder: {exc}") from exc

    def rename_path(self, *, path: str, new_name: str) -> None:
        try:
            source_path = StorageRelativePath.from_raw(path)
            destination_path = source_path.with_name(new_name)
            self._move_between_paths(source_path=source_path, destination_path=destination_path)
        except (ClientError, src_exc.S3ConfigurationError) as exc:
            raise StorageOperationError(f"Failed to rename S3 object: {exc}") from exc

    def move_path(self, *, path: str, target_path: str) -> None:
        try:
            source_path = StorageRelativePath.from_raw(path)
            destination_path = source_path.move_to(target_path)
            self._move_between_paths(source_path=source_path, destination_path=destination_path)
        except (ClientError, src_exc.S3ConfigurationError) as exc:
            raise StorageOperationError(f"Failed to move S3 object: {exc}") from exc

    def delete_files(self, *, paths: list[str]) -> DeleteResult:
        try:
            keys = [self._build_key(path=path) for path in paths]
            result = self._manager.delete_keys(self._bucket, keys)
            return DeleteResult(deleted_count=result["deleted"], errors=result["errors"])
        except ClientError as exc:
            raise StorageOperationError(f"Failed to delete S3 objects: {exc}") from exc

    def delete_folder(self, *, path: str) -> DeleteResult:
        try:
            prefix = self._build_key(path=path, trailing_slash_for_folder=True)
            result = self._manager.delete_prefix(self._bucket, prefix)
            return DeleteResult(deleted_count=result["deleted"], errors=result["errors"])
        except ClientError as exc:
            raise StorageOperationError(f"Failed to delete S3 folder: {exc}") from exc

    def generate_upload_presign(
        self,
        *,
        path: str,
        filename: str,
        content_type_prefix: str,
        expires_seconds: int,
        max_upload_size_bytes: int,
    ) -> PresignedUpload:
        try:
            key = self._build_key(path=path, filename=filename)
            payload = self._manager.presigned_post_exact_key(
                bucket=self._bucket,
                key=key,
                max_size=max_upload_size_bytes,
                expires_seconds=expires_seconds,
                content_type_startswith=content_type_prefix,
            )
            fields = {key: str(value) for key, value in payload["fields"].items()}
            return PresignedUpload(url=payload["url"], fields=fields)
        except (ClientError, src_exc.S3ConfigurationError) as exc:
            raise StorageOperationError(f"Failed to generate S3 upload presign: {exc}") from exc

    def generate_download_presign(self, *, path: str, filename: str, expires_seconds: int) -> str:
        try:
            key = self._build_key(path=path, filename=filename)
            return self._manager.presigned_get(
                bucket=self._bucket,
                key=key,
                expires_seconds=expires_seconds,
            )
        except (ClientError, src_exc.S3ConfigurationError) as exc:
            raise StorageOperationError(f"Failed to generate S3 download presign: {exc}") from exc

    def upload_file(
        self,
        *,
        path: str,
        filename: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        try:
            key = self._build_key(path=path, filename=filename)
            self._manager.put_object(
                bucket=self._bucket,
                key=key,
                body=content,
                content_type=content_type,
            )
        except ClientError as exc:
            raise StorageOperationError(f"Failed to upload S3 object: {exc}") from exc

    def download_file(self, *, path: str, filename: str) -> DownloadedFile:
        try:
            key = self._build_key(path=path, filename=filename)
            content = self._manager.get_object_bytes(bucket=self._bucket, key=key)
            media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
            return DownloadedFile(filename=StorageEntryName.from_raw(filename).value, content=content, media_type=media_type)
        except ClientError as exc:
            raise StorageOperationError(f"Failed to download S3 object: {exc}") from exc
