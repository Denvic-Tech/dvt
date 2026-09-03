from __future__ import annotations

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from core.types import FsCtx

from src.node_dsl.runtime.integrations.file_connection.filesystem import FileConnectionRuntime
from src.node_dsl.runtime.integrations.file_connection.s3 import (
    S3AccessDeniedError,
    S3AuthenticationError,
    S3BucketNotFoundError,
    S3EndpointError,
    S3PathNotFoundError,
    S3RequestError,
)


class _FakeS3FS:
    def __init__(
        self,
        *,
        exists_result: bool = False,
        glob_result: list[str] | None = None,
        path_error: Exception | None = None,
        bucket_error: Exception | None = None,
    ) -> None:
        self.exists_result = exists_result
        self.glob_result = list(glob_result or [])
        self.path_error = path_error
        self.bucket_error = bucket_error
        self.info_calls: list[str] = []

    @staticmethod
    def _strip_protocol(path: str) -> str:
        return path.split("://", 1)[-1].lstrip("/")

    def glob(self, path: str) -> list[str]:
        return list(self.glob_result)

    def info(self, path: str):
        self.info_calls.append(path)
        if path == "reports-bucket":
            if self.bucket_error is not None:
                raise self.bucket_error
            return {"name": path, "type": "directory"}
        if self.path_error is not None:
            raise self.path_error
        if not self.exists_result:
            raise FileNotFoundError(path)
        return {"name": path, "type": "file"}


class _FakeSMBFS:
    def __init__(self, *, glob_result: list[str] | None = None) -> None:
        self.glob_result = list(glob_result or [])

    @staticmethod
    def _strip_protocol(path: str) -> str:
        remainder = path.split("://", 1)[-1]
        slash_index = remainder.find("/")
        return remainder[slash_index:] if slash_index >= 0 else "/"

    def glob(self, path: str) -> list[str]:
        return list(self.glob_result)

    def exists(self, path: str) -> bool:
        return False


def _make_s3_runtime(fs: _FakeS3FS | None = None) -> FileConnectionRuntime:
    return FileConnectionRuntime(
        FsCtx(
            fs=fs or _FakeS3FS(),
            protocol="s3",
            path="s3://reports-bucket/incoming/data.csv",
            storage_options={
                "client_kwargs": {"endpoint_url": "https://s3.example.test"},
            },
            url_root="s3://",
        )
    )


def _client_error(code: str, message: str, status: int = 400) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": message},
            "ResponseMetadata": {
                "HTTPStatusCode": status,
                "RequestId": "request-123",
            },
        },
        "HeadObject",
    )


def test_runtime_translates_filesystem_initialization_error(monkeypatch) -> None:
    ctx = FsCtx(
        fs=None,
        protocol="s3",
        path="s3://reports-bucket/incoming/data.csv",
        storage_options={
            "client_kwargs": {"endpoint_url": "https://s3.example.test"},
        },
        url_root="s3://",
    )

    def _raise_endpoint_error(*_args, **_kwargs):
        raise EndpointConnectionError(endpoint_url="https://s3.example.test")

    monkeypatch.setattr(
        "src.node_dsl.runtime.integrations.file_connection.filesystem.fsspec.filesystem",
        _raise_endpoint_error,
    )

    with pytest.raises(S3EndpointError, match="Failed to connect to S3"):
        FileConnectionRuntime(ctx)


def test_operation_distinguishes_missing_bucket() -> None:
    runtime = _make_s3_runtime()

    with pytest.raises(S3BucketNotFoundError) as exc_info:
        with runtime.operation("reading CSV files"):
            raise _client_error(
                "NoSuchBucket",
                "The specified bucket does not exist",
                404,
            )

    message = str(exc_info.value)
    assert "reports-bucket" in message
    assert "NoSuchBucket" in message
    assert "request-123" in message


def test_operation_distinguishes_missing_object() -> None:
    runtime = _make_s3_runtime()

    with pytest.raises(S3PathNotFoundError) as exc_info:
        with runtime.operation("reading Parquet files"):
            raise _client_error("NoSuchKey", "The specified key does not exist", 404)

    message = str(exc_info.value)
    assert "s3://reports-bucket/incoming/data.csv" in message
    assert "NoSuchKey" in message


def test_operation_distinguishes_access_denied() -> None:
    runtime = _make_s3_runtime()

    with pytest.raises(S3AccessDeniedError) as exc_info:
        with runtime.operation("listing Excel files"):
            raise _client_error("AccessDenied", "Access Denied", 403)

    assert "required S3 permissions" in str(exc_info.value)


def test_operation_distinguishes_invalid_credentials() -> None:
    runtime = _make_s3_runtime()

    with pytest.raises(S3AuthenticationError, match="authentication failed"):
        with runtime.operation("reading JSON file"):
            raise _client_error("InvalidAccessKeyId", "Invalid access key", 403)


def test_operation_reports_endpoint_connection_error() -> None:
    runtime = _make_s3_runtime()

    with pytest.raises(S3EndpointError) as exc_info:
        with runtime.operation("reading CSV files"):
            raise EndpointConnectionError(endpoint_url="https://s3.example.test")

    message = str(exc_info.value)
    assert "Failed to connect to S3" in message
    assert "https://s3.example.test" in message


def test_operation_wraps_unknown_s3_server_error_with_details() -> None:
    runtime = _make_s3_runtime()

    with pytest.raises(S3RequestError) as exc_info:
        with runtime.operation("reading CSV files"):
            raise _client_error("CustomBackendError", "Backend failed", 500)

    message = str(exc_info.value)
    assert "CustomBackendError" in message
    assert "request-123" in message


def test_required_list_does_not_mask_access_denied_as_missing_path() -> None:
    fs = _FakeS3FS(
        path_error=_client_error("AccessDenied", "Access Denied", 403),
    )
    runtime = _make_s3_runtime(fs)

    with pytest.raises(S3AccessDeniedError, match="Access denied by S3"):
        runtime.list_files(
            required=True,
            subject="CSV file(s)",
            operation="listing CSV files",
        )

    assert fs.info_calls == ["reports-bucket/incoming/data.csv"]


def test_required_list_reports_missing_path_when_bucket_is_reachable() -> None:
    fs = _FakeS3FS(exists_result=False)
    runtime = _make_s3_runtime(fs)

    with pytest.raises(S3PathNotFoundError, match="Bucket 'reports-bucket' exists"):
        runtime.list_files(
            required=True,
            subject="CSV file(s)",
            operation="matching CSV files",
        )

    assert fs.info_calls == [
        "reports-bucket/incoming/data.csv",
        "reports-bucket",
    ]


def test_required_list_reports_missing_bucket() -> None:
    fs = _FakeS3FS(
        exists_result=False,
        bucket_error=FileNotFoundError("reports-bucket"),
    )
    runtime = _make_s3_runtime(fs)

    with pytest.raises(S3BucketNotFoundError, match="reports-bucket"):
        runtime.list_files(
            required=True,
            subject="JSON file(s)",
            operation="listing JSON files",
        )

    assert fs.info_calls == [
        "reports-bucket/incoming/data.csv",
        "reports-bucket",
    ]


def test_numeric_404_is_disambiguated_by_checking_bucket() -> None:
    runtime = _make_s3_runtime(_FakeS3FS())

    with pytest.raises(S3PathNotFoundError, match="Bucket 'reports-bucket' exists"):
        with runtime.operation("reading CSV files"):
            raise _client_error("404", "Not Found", 404)


def test_glob_results_are_restored_to_full_urls_for_non_s3_protocols() -> None:
    runtime = FileConnectionRuntime(
        FsCtx(
            fs=_FakeSMBFS(
                glob_result=[
                    "/shared/reports/b.json",
                    "/shared/reports/a.json",
                ]
            ),
            protocol="smb",
            path="smb://fileserver:445/shared/reports/*.json",
            storage_options={},
            host="fileserver",
            port=445,
            url_root="smb://fileserver:445",
        )
    )

    assert runtime.list_files() == [
        "smb://fileserver:445/shared/reports/a.json",
        "smb://fileserver:445/shared/reports/b.json",
    ]
