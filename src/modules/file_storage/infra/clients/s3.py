from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

try:
    import boto3
    from boto3.s3.transfer import TransferConfig
    from botocore.config import Config as BotoConfig
except ImportError:
    boto3 = None
    TransferConfig = None
    BotoConfig = None

from src import exceptions as src_exc


@dataclass(frozen=True, slots=True)
class PreSignedPart:
    url: str
    part_number: int


class S3StorageClient:
    """Module-owned sync client for S3-compatible file operations."""

    def __init__(
        self,
        endpoint_url: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        region_name: str = "garage",
        *,
        aws_session_token: str | None = None,
        use_ssl: bool | None = None,
        verify: bool | str | None = None,
        path_style: bool = False,
        signature_version: str | None = None,
        client: Any | None = None,
        multipart_threshold: int = 50 * 1024 * 1024,
        multipart_chunksize: int = 50 * 1024 * 1024,
        max_concurrency: int = 4,
        use_threads: bool = True,
    ) -> None:
        if client is not None:
            self._client = client
        else:
            if boto3 is None:
                raise RuntimeError("boto3 is required for S3 connections.")

            if not all([endpoint_url, aws_access_key_id, aws_secret_access_key]):
                raise src_exc.S3ConfigurationError(
                    "S3StorageClient requires either a ready client or endpoint/credentials"
                )

            config_kwargs: dict[str, Any] = {}
            if path_style:
                config_kwargs["s3"] = {"addressing_style": "path"}
            if signature_version:
                config_kwargs["signature_version"] = signature_version

            client_kwargs: dict[str, Any] = {
                "endpoint_url": endpoint_url,
                "aws_access_key_id": aws_access_key_id,
                "aws_secret_access_key": aws_secret_access_key,
                "region_name": region_name,
            }
            if config_kwargs:
                if BotoConfig is None:
                    raise RuntimeError("botocore is required for S3 client configuration.")
                client_kwargs["config"] = BotoConfig(**config_kwargs)
            if aws_session_token:
                client_kwargs["aws_session_token"] = aws_session_token
            if use_ssl is not None:
                client_kwargs["use_ssl"] = use_ssl
            if verify is not None:
                client_kwargs["verify"] = verify
            self._client = boto3.client("s3", **client_kwargs)

        if TransferConfig is None:
            raise RuntimeError("boto3 is required for S3 connections.")

        self._transfer_config = TransferConfig(
            multipart_threshold=multipart_threshold,
            multipart_chunksize=multipart_chunksize,
            max_concurrency=max_concurrency,
            use_threads=use_threads,
        )

    @property
    def client(self) -> Any:
        return self._client

    def create_folder(self, bucket: str, key: str) -> dict[str, Any]:
        if not key.endswith("/"):
            key += "/"
        return self._client.put_object(Bucket=bucket, Key=key, Body=b"")

    def put_object(
        self,
        bucket: str,
        key: str,
        body: bytes | bytearray | memoryview,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
        cache_control: str | None = None,
        content_disposition: str | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key, "Body": body}
        if content_type:
            kwargs["ContentType"] = content_type
        if metadata:
            kwargs["Metadata"] = metadata
        if cache_control:
            kwargs["CacheControl"] = cache_control
        if content_disposition:
            kwargs["ContentDisposition"] = content_disposition
        return self._client.put_object(**kwargs)

    def get_object_bytes(self, bucket: str, key: str) -> bytes:
        response = self._client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def head_object(self, bucket: str, key: str) -> dict[str, Any]:
        return self._client.head_object(Bucket=bucket, Key=key)

    def copy_object(self, bucket: str, source_key: str, destination_key: str) -> dict[str, Any]:
        return self._client.copy_object(
            Bucket=bucket,
            Key=destination_key,
            CopySource={"Bucket": bucket, "Key": source_key},
        )

    def delete_object(self, bucket: str, key: str) -> dict[str, Any]:
        return self._client.delete_object(Bucket=bucket, Key=key)

    def list_keys(self, bucket: str, prefix: str, max_keys: int | None = None) -> list[str]:
        paginator = self._client.get_paginator("list_objects_v2")
        paginate_kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
        if max_keys is not None:
            paginate_kwargs["PaginationConfig"] = {"MaxItems": max_keys, "PageSize": min(max_keys, 1000)}

        keys: list[str] = []
        for page in paginator.paginate(**paginate_kwargs):
            for item in page.get("Contents", []) or []:
                keys.append(item["Key"])
                if max_keys is not None and len(keys) >= max_keys:
                    return keys
        return keys

    def upload_file(self, filename_or_fileobj, bucket: str, key: str, extra_args: dict[str, Any] | None = None) -> None:
        if hasattr(filename_or_fileobj, "read"):
            self._client.upload_fileobj(
                filename_or_fileobj,
                bucket,
                key,
                ExtraArgs=extra_args or {},
                Config=self._transfer_config,
            )
            return

        self._client.upload_file(
            str(filename_or_fileobj),
            bucket,
            key,
            ExtraArgs=extra_args or {},
            Config=self._transfer_config,
        )

    def download_file(self, bucket: str, key: str, filename_or_fileobj) -> None:
        if hasattr(filename_or_fileobj, "write"):
            self._client.download_fileobj(bucket, key, filename_or_fileobj, Config=self._transfer_config)
            return
        self._client.download_file(bucket, key, str(filename_or_fileobj), Config=self._transfer_config)

    def delete_prefix(self, bucket: str, prefix: str, max_workers: int = 8) -> dict[str, Any]:
        if prefix and not prefix.endswith("/"):
            prefix += "/"

        paginator = self._client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

        batches: list[list[dict[str, str]]] = []
        current: list[dict[str, str]] = []
        for page in pages:
            for obj in page.get("Contents", []) or []:
                current.append({"Key": obj["Key"]})
                if len(current) == 1000:
                    batches.append(current)
                    current = []
        if current:
            batches.append(current)

        deleted = 0
        errors: list[str] = []

        def _delete_batch(batch: list[dict[str, str]]) -> tuple[int, list[str]]:
            try:
                response = self._client.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": batch, "Quiet": True},
                )
                ok = len(response.get("Deleted", []))
                batch_errors = [
                    f'{item.get("Key")}: {item.get("Code")} {item.get("Message")}'
                    for item in response.get("Errors", []) or []
                ]
                return ok, batch_errors
            except Exception as exc:  # noqa: BLE001
                return 0, [f"batch_failed: {exc}"]

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_delete_batch, batch) for batch in batches]
            for future in as_completed(futures):
                ok, batch_errors = future.result()
                deleted += ok
                errors.extend(batch_errors)

        return {"deleted": deleted, "errors": errors}

    def delete_keys(self, bucket: str, keys: list[str], max_workers: int = 4) -> dict[str, Any]:
        if not keys:
            return {"deleted": 0, "errors": []}

        objects = [{"Key": key} for key in keys]
        batches = [objects[index:index + 1000] for index in range(0, len(objects), 1000)]

        deleted = 0
        errors: list[str] = []

        def _delete_batch(batch: list[dict[str, str]]) -> tuple[int, list[str]]:
            try:
                response = self._client.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": batch, "Quiet": True},
                )
                ok = len(response.get("Deleted", []))
                batch_errors = [
                    f'{item.get("Key")}: {item.get("Code")} {item.get("Message")}'
                    for item in response.get("Errors", []) or []
                ]
                return ok, batch_errors
            except Exception as exc:  # noqa: BLE001
                return 0, [f"batch_failed: {exc}"]

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_delete_batch, batch) for batch in batches]
            for future in as_completed(futures):
                ok, batch_errors = future.result()
                deleted += ok
                errors.extend(batch_errors)

        return {"deleted": deleted, "errors": errors}

    def presigned_post_exact_key(
        self,
        bucket: str,
        key: str,
        *,
        expires_seconds: int = 900,
        min_size: int = 1,
        max_size: int = 50 * 1024 * 1024,
        content_type_startswith: str | None = None,
        cache_control: str | None = None,
        content_disposition: str | None = None,
        extra_fields: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        conditions: list[Any] = [["content-length-range", min_size, max_size]]
        if content_type_startswith:
            conditions.append(["starts-with", "$Content-Type", content_type_startswith])
        if cache_control:
            conditions.append(["eq", "$Cache-Control", cache_control])
        if content_disposition:
            conditions.append(["eq", "$Content-Disposition", content_disposition])

        fields = extra_fields.copy() if extra_fields else {}
        fields.pop("success_action_status", None)
        fields["bucket"] = bucket
        conditions.append({"bucket": bucket})

        return self._client.generate_presigned_post(
            Bucket=bucket,
            Key=key,
            Fields=fields,
            Conditions=conditions,
            ExpiresIn=expires_seconds,
        )

    def presigned_put(
        self,
        bucket: str,
        key: str,
        expires_seconds: int = 900,
        content_type: str | None = None,
        expected_content_length: int | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> str:
        params: dict[str, Any] = {"Bucket": bucket, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        if expected_content_length is not None:
            params["ContentLength"] = expected_content_length
        if extra_headers:
            params.update({name: value for name, value in extra_headers.items()})

        return self._client.generate_presigned_url(
            ClientMethod="put_object",
            Params=params,
            ExpiresIn=expires_seconds,
        )

    def presigned_get(
        self,
        bucket: str,
        key: str,
        expires_seconds: int = 900,
        response_content_type: str | None = None,
        response_content_disposition: str | None = None,
    ) -> str:
        params: dict[str, Any] = {"Bucket": bucket, "Key": key}
        if response_content_type:
            params["ResponseContentType"] = response_content_type
        if response_content_disposition:
            params["ResponseContentDisposition"] = response_content_disposition

        return self._client.generate_presigned_url(
            ClientMethod="get_object",
            Params=params,
            ExpiresIn=expires_seconds,
        )

    def multipart_init(
        self,
        bucket: str,
        key: str,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key}
        if content_type:
            kwargs["ContentType"] = content_type
        if metadata:
            kwargs["Metadata"] = metadata
        response = self._client.create_multipart_upload(**kwargs)
        return response["UploadId"]

    def multipart_presign_part(
        self,
        bucket: str,
        key: str,
        upload_id: str,
        part_number: int,
        expires_seconds: int = 3600,
    ) -> PreSignedPart:
        url = self._client.generate_presigned_url(
            ClientMethod="upload_part",
            Params={
                "Bucket": bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=expires_seconds,
        )
        return PreSignedPart(url=url, part_number=part_number)

    def multipart_list_parts(self, bucket: str, key: str, upload_id: str) -> list[dict[str, Any]]:
        response = self._client.list_parts(Bucket=bucket, Key=key, UploadId=upload_id)
        return response.get("Parts", [])

    def multipart_complete(self, bucket: str, key: str, upload_id: str, etags_in_order: Iterable[str]) -> dict[str, Any]:
        parts = [{"ETag": etag, "PartNumber": index + 1} for index, etag in enumerate(etags_in_order)]
        return self._client.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )

    def multipart_abort(self, bucket: str, key: str, upload_id: str) -> dict[str, Any]:
        return self._client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)

    def multipart_list_uploads(self, bucket: str, prefix: str | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"Bucket": bucket}
        if prefix:
            kwargs["Prefix"] = prefix
        return self._client.list_multipart_uploads(**kwargs)

    @staticmethod
    def user_key(
        user_id: str,
        path: str | None = None,
        filename: str | None = None,
        trailing_slash_for_folder: bool = False,
    ) -> str:
        base = user_id.strip("/")
        parts = [base]
        if path:
            parts.append(path.strip("/"))
        if filename:
            parts.append(filename.strip("/"))
        key = "/".join(parts)
        if (not filename and trailing_slash_for_folder) and not key.endswith("/"):
            key += "/"
        return key
