import asyncio

import sqlalchemy as sa
from fastapi import APIRouter

from core.db.connect.engine import build_engine_from_connection_string
from core.db.ddl.database import (
    AUTOCOMMIT_DATABASE_DIALECTS,
    UNSUPPORTED_DATABASE_DIALECTS,
    build_create_database_sql,
    database_exists,
    execute_create_database,
    quote_database_name,
)

from services.gateway.deps.db_catalog import RedisBytes

from src.exception_registry.utils import safe_exception_message
from src.exceptions import DDLError
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.common import CommonResponse
from src.schemas.http.create_table import CreateDatabaseRequest

from .connection import invalidate_ddl_catalog, resolve_ddl_connection

router = r = APIRouter()


_UNSUPPORTED_DATABASE_DIALECTS = UNSUPPORTED_DATABASE_DIALECTS
_AUTOCOMMIT_DATABASE_DIALECTS = AUTOCOMMIT_DATABASE_DIALECTS


def _quote_database_name(engine: sa.Engine, database_name: str) -> str:
    return quote_database_name(engine, database_name)


def _database_exists(engine: sa.Engine, database_name: str) -> bool:
    try:
        return database_exists(engine, database_name)
    except ValueError as exc:
        raise DDLError(safe_exception_message(exc)) from exc


def _build_create_database_sql(engine: sa.Engine, database_name: str) -> str:
    try:
        return build_create_database_sql(engine, database_name)
    except ValueError as exc:
        raise DDLError(safe_exception_message(exc)) from exc


def create_database_from_connection_string(
    request: CreateDatabaseRequest,
    connection_string: str,
) -> CommonResponse:
    try:
        engine = build_engine_from_connection_string(
            connection_string=connection_string,
        )
    except ValueError as exc:
        detail = safe_exception_message(exc)
        raise DDLError(detail) from exc

    try:
        if _database_exists(engine, request.database_name):
            return CommonResponse(
                success=True,
                message=f"Database \"{request.database_name}\" already exists.",
            )

        sql = _build_create_database_sql(engine, request.database_name)
        execute_create_database(engine, sql)
    except DDLError:
        raise
    except Exception as exc:
        detail = safe_exception_message(exc)
        raise DDLError(f"Failed to create database: {detail}") from exc
    finally:
        engine.dispose()

    return CommonResponse(
        success=True,
        message=f"Database \"{request.database_name}\" created successfully.",
    )


@r.post("/create-database", response_model=CommonResponse)
async def create_database(
    request: CreateDatabaseRequest,
    user: UserAccessOnly,
    redis: RedisBytes,
):
    resolved = await resolve_ddl_connection(request.connection_id, user)
    response = await asyncio.to_thread(
        create_database_from_connection_string,
        request,
        resolved.connection_string,
    )
    await invalidate_ddl_catalog(
        connection_id=resolved.connection_id,
        user=user,
        redis=redis,
    )
    return response
