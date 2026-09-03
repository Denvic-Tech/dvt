from __future__ import annotations

from collections.abc import Iterator

from botocore.exceptions import (
    BotoCoreError,
    ConnectTimeoutError,
    CredentialRetrievalError,
    EndpointConnectionError,
    NoCredentialsError,
    PartialCredentialsError,
    ReadTimeoutError,
    SSLError,
)

from core.types import FsCtx


class S3BucketNotFoundError(FileNotFoundError):
    """S3-бакет не существует или недоступен через настроенный endpoint."""


class S3PathNotFoundError(FileNotFoundError):
    """Путь или объект внутри доступного S3-бакета не найден."""


class S3AccessDeniedError(PermissionError):
    """S3 отклонил запрос из-за отсутствия прав доступа."""


class S3AuthenticationError(PermissionError):
    """S3 отклонил запрос из-за проблем с учетными данными или подписью."""


class S3EndpointError(ConnectionError):
    """Не удалось подключиться к S3 либо endpoint/region настроены некорректно."""


class S3RequestError(OSError):
    """Прочая диагностированная ошибка запроса к S3."""


class S3FileConnectionErrorTranslator:
    """Преобразует botocore/s3fs ошибки в диагностичные runtime-ошибки."""

    _AUTH_ERROR_CODES = {
        "ExpiredToken",
        "InvalidAccessKeyId",
        "InvalidSecurity",
        "InvalidSignature",
        "InvalidToken",
        "RequestTimeTooSkewed",
        "SignatureDoesNotMatch",
        "TokenRefreshRequired",
    }
    _ACCESS_ERROR_CODES = {
        "403",
        "AccessDenied",
        "AccountProblem",
        "AllAccessDisabled",
        "InvalidObjectState",
        "InvalidPayer",
        "NotSignedUp",
    }
    _BUCKET_NOT_FOUND_CODES = {"NoSuchBucket"}
    _PATH_NOT_FOUND_CODES = {"NoSuchKey", "NotFound"}
    _ENDPOINT_OR_REGION_ERROR_CODES = {
        "301",
        "307",
        "AuthorizationHeaderMalformed",
        "PermanentRedirect",
        "Redirect",
        "TemporaryRedirect",
    }
    _RETRYABLE_SERVER_ERROR_CODES = {
        "500",
        "503",
        "InternalError",
        "ServiceUnavailable",
        "SlowDown",
    }

    def __init__(self, ctx: FsCtx) -> None:
        self._ctx = ctx

    @staticmethod
    def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
        seen: set[int] = set()
        current: BaseException | None = exc
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            yield current
            current = current.__cause__ or current.__context__

    @staticmethod
    def _split_path(path: str) -> tuple[str, str]:
        stripped = path.removeprefix("s3://").lstrip("/")
        bucket, separator, key = stripped.partition("/")
        return bucket, key if separator else ""

    def _endpoint(self) -> str | None:
        client_kwargs = self._ctx.storage_options.get("client_kwargs")
        if not isinstance(client_kwargs, dict):
            return None
        endpoint_url = client_kwargs.get("endpoint_url")
        return str(endpoint_url) if endpoint_url else None

    def _client_error_details(
        self,
        exc: BaseException,
    ) -> tuple[str | None, str | None, int | None, str | None]:
        for current in self._exception_chain(exc):
            response = getattr(current, "response", None)
            if not isinstance(response, dict):
                continue

            error = response.get("Error")
            metadata = response.get("ResponseMetadata")
            if not isinstance(error, dict):
                continue

            code = error.get("Code")
            message = error.get("Message")
            status = metadata.get("HTTPStatusCode") if isinstance(metadata, dict) else None
            request_id = metadata.get("RequestId") if isinstance(metadata, dict) else None
            return (
                str(code) if code is not None else None,
                str(message) if message is not None else None,
                int(status) if isinstance(status, int) else None,
                str(request_id) if request_id is not None else None,
            )

        return None, None, None, None

    @staticmethod
    def _format_server_details(
        *,
        code: str | None,
        message: str | None,
        status: int | None,
        request_id: str | None,
    ) -> str:
        details: list[str] = []
        if code:
            details.append(f"code={code}")
        if status is not None:
            details.append(f"status={status}")
        if request_id:
            details.append(f"request_id={request_id}")
        if message:
            details.append(f"message={message}")
        return ", ".join(details)

    def _known_server_error(
        self,
        exc: BaseException,
        *,
        operation: str,
        path: str,
    ) -> BaseException | None:
        bucket, _key = self._split_path(path)
        code, message, status, request_id = self._client_error_details(exc)
        server_details = self._format_server_details(
            code=code,
            message=message,
            status=status,
            request_id=request_id,
        )
        suffix = f" Server response: {server_details}." if server_details else ""

        if code in self._BUCKET_NOT_FOUND_CODES:
            return S3BucketNotFoundError(
                f"S3 bucket '{bucket}' does not exist while {operation}. "
                f"Path: '{path}'.{suffix}"
            )

        if code in self._PATH_NOT_FOUND_CODES:
            return S3PathNotFoundError(
                f"S3 path was not found while {operation}: '{path}'. "
                f"Bucket: '{bucket}'.{suffix}"
            )

        if code in self._AUTH_ERROR_CODES:
            return S3AuthenticationError(
                f"S3 authentication failed while {operation}. Path: '{path}', "
                f"bucket: '{bucket}'. Check access key, secret/session token and system time.{suffix}"
            )

        if code in self._ACCESS_ERROR_CODES:
            return S3AccessDeniedError(
                f"Access denied by S3 while {operation}. Path: '{path}', bucket: '{bucket}'. "
                "Check credentials and required S3 permissions for the requested operation."
                f"{suffix}"
            )

        if code in self._ENDPOINT_OR_REGION_ERROR_CODES:
            endpoint = self._endpoint()
            endpoint_info = f", endpoint: '{endpoint}'" if endpoint else ""
            return S3EndpointError(
                "S3 endpoint, addressing style or region appears to be misconfigured while "
                f"{operation}. Path: '{path}', bucket: '{bucket}'{endpoint_info}.{suffix}"
            )

        if code in self._RETRYABLE_SERVER_ERROR_CODES:
            return S3RequestError(
                f"S3 service could not complete the request while {operation}. Path: '{path}', "
                f"bucket: '{bucket}'. The error may be temporary.{suffix}"
            )

        return None

    def _known_client_error(
        self,
        exc: BaseException,
        *,
        operation: str,
        path: str,
    ) -> BaseException | None:
        bucket, _key = self._split_path(path)
        endpoint = self._endpoint()

        for current in self._exception_chain(exc):
            if isinstance(
                current,
                (NoCredentialsError, PartialCredentialsError, CredentialRetrievalError),
            ):
                return S3AuthenticationError(
                    f"S3 credentials are missing or incomplete while {operation}. "
                    f"Path: '{path}', bucket: '{bucket}'. Original error: {current}"
                )

            if isinstance(
                current,
                (EndpointConnectionError, ConnectTimeoutError, ReadTimeoutError, SSLError),
            ):
                endpoint_info = f" Endpoint: '{endpoint}'." if endpoint else ""
                return S3EndpointError(
                    f"Failed to connect to S3 while {operation}. Path: '{path}', "
                    f"bucket: '{bucket}'.{endpoint_info} Original error: {current}"
                )

        return None

    def translate(
        self,
        exc: BaseException,
        *,
        operation: str,
        path: str,
    ) -> BaseException:
        known = self._known_server_error(exc, operation=operation, path=path)
        if known is not None:
            return known

        code, message, status, request_id = self._client_error_details(exc)
        if code == "404":
            return self.missing(operation=operation, path=path, subject="Path")

        client_side = self._known_client_error(exc, operation=operation, path=path)
        if client_side is not None:
            return client_side

        if code is not None:
            bucket, _key = self._split_path(path)
            server_details = self._format_server_details(
                code=code,
                message=message,
                status=status,
                request_id=request_id,
            )
            return S3RequestError(
                f"S3 request failed while {operation}. Path: '{path}', bucket: '{bucket}'. "
                f"Server response: {server_details}."
            )

        if isinstance(exc, FileNotFoundError):
            return self.missing(operation=operation, path=path, subject="Path")

        if isinstance(exc, PermissionError):
            bucket, _key = self._split_path(path)
            return S3AccessDeniedError(
                f"Access denied by S3 while {operation}. Path: '{path}', bucket: '{bucket}'. "
                f"Check credentials and required S3 permissions. Original error: {exc}"
            )

        if isinstance(exc, BotoCoreError):
            bucket, _key = self._split_path(path)
            return S3RequestError(
                f"S3 client error while {operation}. Path: '{path}', bucket: '{bucket}'. "
                f"Original error: {exc}"
            )

        return exc

    def missing(
        self,
        *,
        operation: str,
        path: str,
        subject: str,
    ) -> BaseException:
        bucket, _key = self._split_path(path)
        if not bucket:
            return S3PathNotFoundError(f"Invalid S3 path while {operation}: '{path}'.")

        bucket_path = f"s3://{bucket}"
        try:
            self._ctx.fs.info(bucket)
        except FileNotFoundError as exc:
            known = self._known_server_error(
                exc,
                operation=f"checking bucket '{bucket}'",
                path=bucket_path,
            )
            if isinstance(known, (S3AccessDeniedError, S3AuthenticationError, S3EndpointError)):
                return known
            return S3BucketNotFoundError(
                f"S3 bucket '{bucket}' does not exist or is not visible through the configured "
                f"endpoint while {operation}. Requested path: '{path}'."
            )
        except PermissionError as exc:
            known = self._known_server_error(
                exc,
                operation=f"checking bucket '{bucket}'",
                path=bucket_path,
            )
            if known is not None:
                return known
            return S3AccessDeniedError(
                f"Cannot verify S3 bucket '{bucket}' while {operation}: access was denied. "
                f"Requested path: '{path}'. Check permission to inspect the bucket. "
                f"Original error: {exc}"
            )
        except Exception as exc:  # noqa: BLE001
            known = self._known_server_error(
                exc,
                operation=f"checking bucket '{bucket}'",
                path=bucket_path,
            ) or self._known_client_error(
                exc,
                operation=f"checking bucket '{bucket}'",
                path=bucket_path,
            )
            if known is not None:
                return known
            return S3RequestError(
                f"Failed to verify S3 bucket '{bucket}' while {operation}. "
                f"Requested path: '{path}'. Original error: {exc}"
            )

        return S3PathNotFoundError(
            f"{subject} was not found in S3 while {operation}: '{path}'. "
            f"Bucket '{bucket}' exists and is reachable."
        )
