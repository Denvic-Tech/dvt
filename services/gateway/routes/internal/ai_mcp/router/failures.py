"""Translate exceptions to the existing response and audit outcome; no I/O."""

from dataclasses import dataclass

from src.modules.db_catalog.domain.exceptions import (
    CatalogCacheUnavailableError,
    CatalogConnectionUnavailableError,
    CatalogRequestValidationError,
    CatalogSourceTimeoutError,
    CatalogSourceUnavailableError,
    CatalogTableNotFoundError,
    CatalogUnsupportedError,
)
from src.modules.file_storage.domain.exceptions import FileStorageDomainError
from src.modules.file_storage.flow.exceptions import (
    FileTooLargeError,
    StorageConnectionNotFoundError,
    StorageOperationError,
    UnsupportedStorageBackendError,
    UnsupportedTransferStrategyError,
)

from ..errors import AIMCPHTTPError
from .registry import ValidationErrorCode

# Preserve exception precedence, status, code and sanitized message.
_ERROR_RESPONSES = (
    (
        (CatalogSourceTimeoutError,),
        504,
        "QUERY_TIMEOUT",
        "Catalog request timed out.",
    ),
    (
        (CatalogRequestValidationError,),
        422,
        "GRAPH_VALIDATION_FAILED",
        "Catalog request arguments are invalid.",
    ),
    (
        (
            CatalogConnectionUnavailableError,
            CatalogTableNotFoundError,
            CatalogUnsupportedError,
            StorageConnectionNotFoundError,
        ),
        404,
        "CONNECTION_NOT_FOUND_OR_DENIED",
        "Connection or catalog object is unavailable.",
    ),
    (
        (
            FileStorageDomainError,
            FileTooLargeError,
            UnsupportedStorageBackendError,
            UnsupportedTransferStrategyError,
        ),
        422,
        "STORAGE_PREVIEW_UNSUPPORTED",
        "Storage operation or preview is not supported.",
    ),
    (
        (CatalogCacheUnavailableError, CatalogSourceUnavailableError, StorageOperationError),
        503,
        "GATEWAY_UNAVAILABLE",
        "Gateway dependency is unavailable.",
    ),
)


@dataclass(frozen=True)
class ToolFailure:
    response: AIMCPHTTPError
    outcome: str
    log_message: str | None = None


def translate_failure(exc: Exception, validation_error_code: ValidationErrorCode) -> ToolFailure:
    if isinstance(exc, AIMCPHTTPError):
        return ToolFailure(exc, str(exc.detail.get("code", "error")))
    for exception_types, status, code, message in _ERROR_RESPONSES:
        if isinstance(exc, exception_types):
            return ToolFailure(AIMCPHTTPError(status, code, message), code)
    if isinstance(exc, TypeError):
        return ToolFailure(
            AIMCPHTTPError(500, "GATEWAY_UNAVAILABLE", "Gateway operation failed."),
            "GATEWAY_UNAVAILABLE",
            "AI MCP tool contract mismatch: tool={} correlation_id={} exception_type={}",
        )
    # Pydantic ValidationError is also a ValueError.
    if isinstance(exc, ValueError):
        return ToolFailure(
            AIMCPHTTPError(
                422, validation_error_code, "Tool arguments or graph changes are invalid."
            ),
            validation_error_code,
        )
    return ToolFailure(
        AIMCPHTTPError(500, "GATEWAY_UNAVAILABLE", "Gateway operation failed."),
        "internal_error",
        "AI MCP internal tool failed: tool={} correlation_id={} exception_type={}",
    )
