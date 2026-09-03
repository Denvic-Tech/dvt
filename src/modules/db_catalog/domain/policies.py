from __future__ import annotations

import base64
import hashlib
import json

from .entities import AuthorizedCatalogConnection, CatalogCapabilities
from .exceptions import CatalogRequestValidationError, CatalogUnsupportedError
from .types import CatalogOperation
from .value_objects import CatalogRequest, CatalogTablePreviewRequest


def capabilities_for_dialect(dialect: str) -> CatalogCapabilities:
    normalized = dialect.lower()
    if normalized == "mongodb":
        raise CatalogUnsupportedError("MongoDB catalog is not supported by the SQL fast path.")
    if normalized not in {
        "postgresql",
        "mysql",
        "mariadb",
        "mssql",
        "sqlserver",
        "clickhouse",
        "oracle",
        "sqlite",
    }:
        raise CatalogUnsupportedError(f"Unsupported SQL catalog dialect: {normalized}.")
    return CatalogCapabilities(
        supports_databases=normalized
        in {"postgresql", "mysql", "mariadb", "mssql", "sqlserver", "clickhouse"},
        supports_schemas=normalized in {"postgresql", "mssql", "sqlserver", "oracle", "sqlite"},
    )


def validate_request(
    connection: AuthorizedCatalogConnection,
    request: CatalogRequest,
) -> CatalogCapabilities:
    capabilities = capabilities_for_dialect(connection.dialect)
    if not 1 <= request.limit <= capabilities.max_page_size:
        raise CatalogRequestValidationError(
            f"Catalog page limit must be between 1 and {capabilities.max_page_size}."
        )
    if request.search is not None and len(request.search) > 128:
        raise CatalogRequestValidationError("Catalog search must not exceed 128 characters.")
    if request.operation == CatalogOperation.DATABASES and not capabilities.supports_databases:
        raise CatalogUnsupportedError("Database level is not supported for this dialect.")
    if request.operation == CatalogOperation.SCHEMAS and not capabilities.supports_schemas:
        raise CatalogUnsupportedError("Schema level is not supported for this dialect.")
    if request.operation == CatalogOperation.TABLE and not request.table_name:
        raise CatalogRequestValidationError("table_name is required for table details.")
    return capabilities


def validate_table_preview_request(
    connection: AuthorizedCatalogConnection,
    request: CatalogTablePreviewRequest,
) -> CatalogCapabilities:
    capabilities = capabilities_for_dialect(connection.dialect)
    if not request.table_name:
        raise CatalogRequestValidationError("table_name is required for table preview.")
    return capabilities


def encode_cursor(normalized_name: str, exact_name: str) -> str:
    payload = json.dumps(
        {"v": 1, "n": normalized_name, "e": exact_name},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[str, str] | None:
    if cursor is None:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if payload.get("v") != 1:
            raise ValueError
        return str(payload["n"]), str(payload["e"])
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogRequestValidationError("Invalid catalog cursor.") from exc


def build_cache_key(
    connection: AuthorizedCatalogConnection,
    request: CatalogRequest,
    epoch: int,
) -> str:
    canonical = {
        "operation": request.operation.value,
        "database": request.database_name,
        "schema": request.schema_name,
        "table": request.table_name,
        "search": request.search,
        "cursor": request.cursor,
        "limit": request.limit,
        "kinds": sorted(kind.value for kind in request.kinds),
    }
    request_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()
    revision_hash = hashlib.sha256(connection.revision.encode()).hexdigest()[:16]
    return f"dvt:db-catalog:v1:{connection.id}:{revision_hash}:{epoch}:{request_hash}"
