from dataclasses import dataclass
from functools import lru_cache

from redis.asyncio import Redis

from .flow import (
    CatalogProvider,
    GetTablePreviewUseCase,
    GetTableUseCase,
    ListDatabasesUseCase,
    ListSchemasUseCase,
    ListTablesUseCase,
    RefreshCatalogUseCase,
)
from .infra.gateways import (
    DVTConnectionAccessGateway,
    ResilientValkeyCatalogCache,
    SQLAlchemyCatalogSource,
)


@dataclass(frozen=True, slots=True)
class CatalogUseCases:
    list_databases: ListDatabasesUseCase
    list_schemas: ListSchemasUseCase
    list_tables: ListTablesUseCase
    get_table: GetTableUseCase
    get_table_preview: GetTablePreviewUseCase
    refresh: RefreshCatalogUseCase


def build_catalog_use_cases(
    *,
    connection_service,
    redis: Redis,
    cache_ttl_seconds: int,
    connect_timeout_seconds: int,
    query_timeout_seconds: int,
    request_timeout_seconds: int,
    lock_ttl_seconds: int,
    max_concurrency: int,
    preview_cell_max_chars: int,
    preview_max_response_bytes: int,
) -> CatalogUseCases:
    connection_access = DVTConnectionAccessGateway(connection_service)
    source = _build_catalog_source(
        connect_timeout_seconds,
        query_timeout_seconds,
        request_timeout_seconds,
        max_concurrency,
        preview_cell_max_chars,
        preview_max_response_bytes,
    )
    provider = CatalogProvider(
        connection_access=connection_access,
        source=source,
        cache=ResilientValkeyCatalogCache(redis),
        cache_ttl_seconds=cache_ttl_seconds,
        lock_ttl_seconds=lock_ttl_seconds,
    )
    return CatalogUseCases(
        list_databases=ListDatabasesUseCase(provider),
        list_schemas=ListSchemasUseCase(provider),
        list_tables=ListTablesUseCase(provider),
        get_table=GetTableUseCase(provider),
        get_table_preview=GetTablePreviewUseCase(
            connection_access=connection_access,
            source=source,
        ),
        refresh=RefreshCatalogUseCase(provider),
    )


@lru_cache
def _build_catalog_source(
    connect_timeout_seconds: int,
    query_timeout_seconds: int,
    request_timeout_seconds: int,
    max_concurrency: int,
    preview_cell_max_chars: int,
    preview_max_response_bytes: int,
) -> SQLAlchemyCatalogSource:
    return SQLAlchemyCatalogSource(
        connect_timeout_seconds=connect_timeout_seconds,
        query_timeout_seconds=query_timeout_seconds,
        request_timeout_seconds=request_timeout_seconds,
        max_concurrency=max_concurrency,
        preview_cell_max_chars=preview_cell_max_chars,
        preview_max_response_bytes=preview_max_response_bytes,
    )
