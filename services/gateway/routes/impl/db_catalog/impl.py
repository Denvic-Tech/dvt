from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from services.gateway.deps.db_catalog import (
    RedisBytes,
    build_catalog_actor as _actor,
    get_catalog_use_cases as _use_cases,
)
from services.gateway.metrics.runtime import observe_db_catalog_request

from src.logger import logger
from src.modules.db_catalog import CatalogTableKind
from src.modules.db_catalog.domain import (
    CatalogConnectionUnavailableError,
    CatalogPreviewTooLargeError,
    CatalogRequestValidationError,
    CatalogResponse,
    CatalogSourceTimeoutError,
    CatalogSourceUnavailableError,
    CatalogTableNotFoundError,
    CatalogTablePreviewResponse,
    CatalogUnsupportedError,
)
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly

from .schemas import (
    CatalogColumnSchema,
    CatalogDatabasePageSchema,
    CatalogDatabaseSummarySchema,
    CatalogMetaSchema,
    CatalogRefreshResponseSchema,
    CatalogSchemaPageSchema,
    CatalogSchemaSummarySchema,
    CatalogTableDetailsResponseSchema,
    CatalogTableDetailsSchema,
    CatalogTablePageSchema,
    CatalogTablePreviewColumnSchema,
    CatalogTablePreviewResponseSchema,
    CatalogTableSummarySchema,
)

router = APIRouter(tags=["DB Catalog"])


def _meta(response: CatalogResponse) -> CatalogMetaSchema:
    return CatalogMetaSchema(
        catalog_version=response.catalog_version,
        loaded_at=response.loaded_at,
        expires_at=response.expires_at,
        cache_status=response.cache_status.value,
    )


def _table_summary(item) -> CatalogTableSummarySchema:
    return CatalogTableSummarySchema(
        name=item.name,
        kind=item.kind.value,
        database_name=item.database_name,
        schema_name=item.schema_name,
    )


def _map_error(exc: Exception) -> HTTPException:  # noqa: PLR0911
    if isinstance(exc, CatalogConnectionUnavailableError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="DB connection not found."
        )
    if isinstance(exc, CatalogTableNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DB table not found.")
    if isinstance(exc, CatalogPreviewTooLargeError):
        return HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="DB table preview exceeds the response size limit.",
        )
    if isinstance(exc, (CatalogUnsupportedError, CatalogRequestValidationError)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, CatalogSourceTimeoutError):
        return HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="DB catalog request timed out."
        )
    if isinstance(exc, CatalogSourceUnavailableError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="DB catalog source is unavailable."
        )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="DB catalog request failed."
    )


async def _execute(call, *, operation: str):
    started_at = time.perf_counter()
    try:
        response = await call
    except (
        CatalogConnectionUnavailableError,
        CatalogPreviewTooLargeError,
        CatalogRequestValidationError,
        CatalogSourceTimeoutError,
        CatalogSourceUnavailableError,
        CatalogTableNotFoundError,
        CatalogUnsupportedError,
    ) as exc:
        duration = time.perf_counter() - started_at
        observe_db_catalog_request(
            dialect="unknown",
            operation=operation,
            cache_status="bypass",
            outcome=type(exc).__name__,
            duration_seconds=duration,
        )
        logger.warning(
            "DB catalog request failed",
            operation=operation,
            outcome=type(exc).__name__,
            duration_ms=round(duration * 1000, 3),
        )
        raise _map_error(exc) from None
    duration = time.perf_counter() - started_at
    if isinstance(response, CatalogResponse):
        item_count = len(response.result.items) + int(response.result.table is not None)
        payload_bytes = len(
            json.dumps(asdict(response.result), ensure_ascii=False, default=str).encode("utf-8")
        )
        observe_db_catalog_request(
            dialect=response.dialect,
            operation=operation,
            cache_status=response.cache_status.value,
            outcome="success",
            duration_seconds=duration,
            item_count=item_count,
            payload_bytes=payload_bytes,
        )
        logger.info(
            "DB catalog request completed",
            dialect=response.dialect,
            operation=operation,
            cache_status=response.cache_status.value,
            duration_ms=round(duration * 1000, 3),
            item_count=item_count,
            payload_bytes=payload_bytes,
        )
    elif isinstance(response, CatalogTablePreviewResponse):
        item_count = len(response.preview.rows)
        payload_bytes = len(
            json.dumps(asdict(response.preview), ensure_ascii=False, default=str).encode("utf-8")
        )
        observe_db_catalog_request(
            dialect=response.dialect,
            operation=operation,
            cache_status="bypass",
            outcome="success",
            duration_seconds=duration,
            item_count=item_count,
            payload_bytes=payload_bytes,
        )
        logger.info(
            "DB table preview request completed",
            dialect=response.dialect,
            operation=operation,
            cache_status="bypass",
            duration_ms=round(duration * 1000, 3),
            item_count=item_count,
            payload_bytes=payload_bytes,
            truncated=response.preview.truncated,
        )
    else:
        observe_db_catalog_request(
            dialect="unknown",
            operation=operation,
            cache_status="bypass",
            outcome="success",
            duration_seconds=duration,
        )
    return response


@router.get("/{connection_id}/catalog/databases", response_model=CatalogDatabasePageSchema)
async def list_databases(
    connection_id: str,
    user: UserAccessOnly,
    redis: RedisBytes,
    search: Annotated[str | None, Query(max_length=128)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> CatalogDatabasePageSchema:
    response = await _execute(
        _use_cases(redis).list_databases.execute(
            connection_id=connection_id,
            actor=_actor(user),
            search=search,
            cursor=cursor,
            limit=limit,
        ),
        operation="databases",
    )
    return CatalogDatabasePageSchema(
        items=[
            CatalogDatabaseSummarySchema(name=item.name, is_current=item.is_current)
            for item in response.result.items
        ],
        next_cursor=response.result.next_cursor,
        meta=_meta(response),
    )


@router.get("/{connection_id}/catalog/schemas", response_model=CatalogSchemaPageSchema)
async def list_schemas(
    connection_id: str,
    user: UserAccessOnly,
    redis: RedisBytes,
    database_name: str | None = None,
    search: Annotated[str | None, Query(max_length=128)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> CatalogSchemaPageSchema:
    response = await _execute(
        _use_cases(redis).list_schemas.execute(
            connection_id=connection_id,
            actor=_actor(user),
            database_name=database_name,
            search=search,
            cursor=cursor,
            limit=limit,
        ),
        operation="schemas",
    )
    return CatalogSchemaPageSchema(
        items=[
            CatalogSchemaSummarySchema(name=item.name, database_name=item.database_name)
            for item in response.result.items
        ],
        next_cursor=response.result.next_cursor,
        meta=_meta(response),
    )


@router.get("/{connection_id}/catalog/tables", response_model=CatalogTablePageSchema)
async def list_tables(
    connection_id: str,
    user: UserAccessOnly,
    redis: RedisBytes,
    database_name: str | None = None,
    schema_name: str | None = None,
    search: Annotated[str | None, Query(max_length=128)] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    kinds: Annotated[list[CatalogTableKind] | None, Query()] = None,
) -> CatalogTablePageSchema:
    response = await _execute(
        _use_cases(redis).list_tables.execute(
            connection_id=connection_id,
            actor=_actor(user),
            database_name=database_name,
            schema_name=schema_name,
            search=search,
            cursor=cursor,
            limit=limit,
            kinds=tuple(kinds) if kinds else (CatalogTableKind.TABLE, CatalogTableKind.VIEW),
        ),
        operation="tables",
    )
    return CatalogTablePageSchema(
        items=[_table_summary(item) for item in response.result.items],
        next_cursor=response.result.next_cursor,
        meta=_meta(response),
    )


@router.get("/{connection_id}/catalog/table", response_model=CatalogTableDetailsResponseSchema)
async def get_table(
    connection_id: str,
    table_name: str,
    user: UserAccessOnly,
    redis: RedisBytes,
    database_name: str | None = None,
    schema_name: str | None = None,
) -> CatalogTableDetailsResponseSchema:
    response = await _execute(
        _use_cases(redis).get_table.execute(
            connection_id=connection_id,
            actor=_actor(user),
            database_name=database_name,
            schema_name=schema_name,
            table_name=table_name,
        ),
        operation="table",
    )
    item = response.result.table
    if item is None:
        raise HTTPException(status_code=500, detail="DB catalog returned no table details.")
    return CatalogTableDetailsResponseSchema(
        item=CatalogTableDetailsSchema(
            **_table_summary(item).model_dump(),
            columns=[
                CatalogColumnSchema(
                    name=column.name,
                    ordinal=column.ordinal,
                    dtype=column.dtype,
                    nullable=column.nullable,
                    indexed=column.indexed,
                    primary_key=column.primary_key,
                    indexes=list(column.indexes),
                )
                for column in item.columns
            ],
        ),
        meta=_meta(response),
    )


@router.get(
    "/{connection_id}/catalog/table/preview",
    response_model=CatalogTablePreviewResponseSchema,
)
async def get_table_preview(
    connection_id: str,
    table_name: str,
    user: UserAccessOnly,
    redis: RedisBytes,
    database_name: str | None = None,
    schema_name: str | None = None,
) -> CatalogTablePreviewResponseSchema:
    response = await _execute(
        _use_cases(redis).get_table_preview.execute(
            connection_id=connection_id,
            actor=_actor(user),
            database_name=database_name,
            schema_name=schema_name,
            table_name=table_name,
        ),
        operation="table_preview",
    )
    return CatalogTablePreviewResponseSchema(
        columns=[
            CatalogTablePreviewColumnSchema(name=column.name, dtype=column.dtype)
            for column in response.preview.columns
        ],
        rows=[list(row) for row in response.preview.rows],
        truncated=response.preview.truncated,
    )


@router.post("/{connection_id}/catalog/refresh", response_model=CatalogRefreshResponseSchema)
async def refresh_catalog(
    connection_id: str,
    user: UserAccessOnly,
    redis: RedisBytes,
) -> CatalogRefreshResponseSchema:
    result = await _execute(
        _use_cases(redis).refresh.execute(connection_id=connection_id, actor=_actor(user)),
        operation="refresh",
    )
    return CatalogRefreshResponseSchema(catalog_version=result.catalog_version)
