"""Semantic storage facade for extension code."""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, BinaryIO

from db_connection.registry.defaults import S3Properties, S3Secrets

from core.types import FsCtx

from src.modules.file_storage.infra.clients import S3StorageClient as _S3StorageClient
from src.node_dsl.connection_types import FileConnectionRecord, S3ConnectionRecord
from src.node_dsl.runtime.connections import resolve_file_fs_context


def resolve_file_connection_context(
    connection: FileConnectionRecord,
    *,
    path: str | None = None,
    root_only: bool = False,
    create_fs: bool = True,
    timeout_sec: int | None = None,
) -> FsCtx:
    return resolve_file_fs_context(
        connection,
        path=path,
        root_only=root_only,
        create_fs=create_fs,
        timeout_sec=timeout_sec,
    )


class S3Client:
    """Supported S3 operations without exposing the underlying boto client."""

    def __init__(self, client: _S3StorageClient):
        self._client = client

    @classmethod
    def from_connection(
        cls,
        connection: S3ConnectionRecord,
        *,
        fs_context: FsCtx | None = None,
    ) -> "S3Client":
        context = fs_context or resolve_file_connection_context(
            connection, root_only=True, create_fs=False
        )
        properties = S3Properties.model_validate(connection.properties)
        secrets = S3Secrets.model_validate(connection.secrets)
        client_kwargs = context.storage_options.get("client_kwargs") or {}
        return cls(
            _S3StorageClient(
                endpoint_url=properties.endpoint_url,
                aws_access_key_id=secrets.access_token_id,
                aws_secret_access_key=secrets.access_token_key,
                region_name=properties.region_name or "garage",
                aws_session_token=secrets.session_token,
                use_ssl=properties.use_ssl,
                verify=client_kwargs.get("verify", properties.verify),
                path_style=properties.path_style,
                signature_version=properties.signature_version,
            )
        )

    def iter_objects(self, bucket: str, prefix: str = "") -> Iterator[dict[str, Any]]:
        paginator = self._client.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            yield from page.get("Contents", []) or []

    def list_objects(self, bucket: str, prefix: str = "") -> list[dict[str, Any]]:
        return list(self.iter_objects(bucket, prefix))

    def list_keys(self, bucket: str, prefix: str = "", max_keys: int | None = None) -> list[str]:
        return self._client.list_keys(bucket, prefix, max_keys=max_keys)

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        return self._client.head_object(bucket, key)

    def put_object(self, bucket: str, key: str, body: bytes, **kwargs) -> dict[str, Any]:
        return self._client.put_object(bucket, key, body, **kwargs)

    def copy_object(self, bucket: str, source_key: str, destination_key: str) -> dict[str, Any]:
        return self._client.copy_object(bucket, source_key, destination_key)

    def delete_object(self, bucket: str, key: str) -> dict[str, Any]:
        return self._client.delete_object(bucket, key)

    def upload_file(
        self,
        filename_or_fileobj: str | Path | BinaryIO,
        bucket: str,
        key: str,
        extra_args: dict[str, Any] | None = None,
    ) -> None:
        self._client.upload_file(filename_or_fileobj, bucket, key, extra_args=extra_args)

    def download_file(
        self,
        bucket: str,
        key: str,
        filename_or_fileobj: str | Path | BinaryIO,
    ) -> None:
        self._client.download_file(bucket, key, filename_or_fileobj)


def create_s3_client(
    connection: S3ConnectionRecord, *, fs_context: FsCtx | None = None
) -> S3Client:
    return S3Client.from_connection(connection, fs_context=fs_context)


__all__ = [
    "FileConnectionRecord",
    "FsCtx",
    "S3Client",
    "S3ConnectionRecord",
    "create_s3_client",
    "resolve_file_connection_context",
]
