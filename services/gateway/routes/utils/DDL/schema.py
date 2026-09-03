import asyncio

import sqlalchemy as sa
from fastapi import APIRouter

from core.db.ddl import build_engine_from_connection_string
from core.db.ddl.schema import (
    DIALECTS_WITHOUT_SCHEMA_SUPPORT,
    build_create_schema_sql,
    execute_create_schema,
)

from services.gateway.deps.db_catalog import RedisBytes

from src.exception_registry.utils import safe_exception_message
from src.exceptions import DDLError
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.common import CommonResponse
from src.schemas.http.create_table import (
    CreateSchemaRequest,
    GenerateSchemaDDLRequest,
    GenerateSchemaDDLResponse,
)

from .connection import invalidate_ddl_catalog, resolve_ddl_connection

router = r = APIRouter()


_UNSUPPORTED_SCHEMA_DIALECTS = DIALECTS_WITHOUT_SCHEMA_SUPPORT


def _build_create_schema_sql(engine: sa.Engine, schema_name: str) -> str:
    try:
        return build_create_schema_sql(engine, schema_name)
    except ValueError as exc:
        raise DDLError(safe_exception_message(exc)) from exc


def _execute_create_schema(engine: sa.Engine, schema_name: str) -> None:
    try:
        execute_create_schema(engine, schema_name)
    except ValueError as exc:
        raise DDLError(safe_exception_message(exc)) from exc


def create_schema_from_connection_string(
    request: CreateSchemaRequest,
    connection_string: str,
) -> CommonResponse:
    try:
        engine = build_engine_from_connection_string(
            connection_string=connection_string,
            database_name=request.database_name,
        )
    except ValueError as exc:
        detail = safe_exception_message(exc)
        raise DDLError(detail) from exc

    try:
        inspector = sa.inspect(engine)
        if inspector.has_schema(request.schema_name):
            return CommonResponse(
                success=True,
                message=f"Schema \"{request.schema_name}\" already exists.",
            )

        _execute_create_schema(engine, request.schema_name)
    except DDLError:
        raise
    except NotImplementedError as exc:
        detail = safe_exception_message(exc)
        raise DDLError(f"Schema inspection is not supported for this dialect: {detail}") from exc
    except Exception as exc:
        detail = safe_exception_message(exc)
        raise DDLError(f"Failed to create schema: {detail}") from exc
    finally:
        engine.dispose()

    return CommonResponse(
        success=True,
        message=f"Schema \"{request.schema_name}\" created successfully.",
    )


def _generate_schema_ddl_request(
    request: GenerateSchemaDDLRequest,
    connection_string: str,
) -> GenerateSchemaDDLResponse:
    engine: sa.Engine | None = None
    try:
        engine = build_engine_from_connection_string(
            connection_string=connection_string,
            database_name=request.database_name,
        )
        sql = _build_create_schema_sql(engine, request.schema_name)
    except DDLError:
        raise
    except ValueError as exc:
        detail = safe_exception_message(exc)
        raise DDLError(detail) from exc
    except Exception as exc:
        detail = safe_exception_message(exc)
        raise DDLError(f"Failed to generate schema DDL: {detail}") from exc
    finally:
        if engine is not None:
            engine.dispose()

    if not sql.endswith(";"):
        sql += ";"

    return GenerateSchemaDDLResponse(sql=sql)


@r.post("/create-schema", response_model=CommonResponse)
async def create_schema(
    request: CreateSchemaRequest,
    user: UserAccessOnly,
    redis: RedisBytes,
):
    resolved = await resolve_ddl_connection(request.connection_id, user)
    response = await asyncio.to_thread(
        create_schema_from_connection_string,
        request,
        resolved.connection_string,
    )
    await invalidate_ddl_catalog(
        connection_id=resolved.connection_id,
        user=user,
        redis=redis,
    )
    return response


@r.post("/generate-schema-ddl", response_model=GenerateSchemaDDLResponse)
async def generate_schema_ddl(
    request: GenerateSchemaDDLRequest,
    user: UserAccessOnly,
):
    resolved = await resolve_ddl_connection(request.connection_id, user)
    return await asyncio.to_thread(
        _generate_schema_ddl_request,
        request,
        resolved.connection_string,
    )
