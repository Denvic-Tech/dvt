import asyncio

import sqlalchemy as sa
from fastapi import APIRouter

from core.db.connect.engine import build_engine_from_connection_string
from core.db.ddl.column_actions import apply_table_column_actions
from core.db.ddl.schema import DIALECTS_WITHOUT_SCHEMA_SUPPORT, ensure_schema_exists
from core.db.ddl.table import (
    create_typed_table_from_columns,
    execute_raw_create_table_sql,
    generate_create_table_ddl_from_columns,
    generate_create_table_ddl_from_metadata,
    normalize_db_columns_nullable_for_ddl,
    resolve_metadata_schema_for_ddl,
    validate_create_table_sql_target,
)
from core.db.ddl.table_recreate import recreate_table_safely
from core.db.write_v4 import (
    resolve_existing_table_write_columns,
    resolve_typed_create_write_columns,
)
from core.db.write_v4.dialects import resolve_dialect
from core.metadata.db_metadata import load_db_table_metadata
from core.types import DBColumn

from services.gateway.deps.db_catalog import RedisBytes

from src.exception_registry.utils import safe_exception_message
from src.exceptions import (
    ApplyTableColumnActionsError,
    CreateTableError,
    RecreateTableError,
    ResolveWriteColumnsError,
    TruncateTableError,
)
from src.logger import logger
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.schemas.http.common import CommonResponse
from src.schemas.http.create_table import (
    ApplyTableColumnActionsRequest,
    ApplyTableColumnActionsResponse,
    CreateTableFromSchemaRequest,
    CreateTableFromSQLRequest,
    CreateTableRequest,
    GenerateTableDDL,
    GenerateTableDDLResponse,
    RecreateTableRequest,
    ResolveWriteColumnsRequest,
    ResolveWriteColumnsResponse,
    TableDDLActionResponse,
    TruncateTableRequest,
)

from .connection import invalidate_ddl_catalog, resolve_ddl_connection

router = r = APIRouter()


_DIALECTS_WITHOUT_SCHEMA_SUPPORT = DIALECTS_WITHOUT_SCHEMA_SUPPORT
_RESOLVE_WRITE_COLUMNS_CONNECT_TIMEOUT_SEC = 25
_RESOLVE_WRITE_COLUMNS_REQUEST_TIMEOUT_SEC = 30


def _resolve_metadata_schema_for_ddl(
    *,
    dialect_name: str,
    schema_name: str | None,
    database_name: str | None,
) -> str | None:
    return resolve_metadata_schema_for_ddl(
        dialect_name=dialect_name,
        schema_name=schema_name,
        database_name=database_name,
    )


def _normalize_db_columns_nullable_for_ddl(
    *,
    dialect_name: str,
    columns: list[DBColumn],
    primary_key_cols: str | list[str] | None,
    preserve_input_nullable: bool = False,
) -> list[DBColumn]:
    return normalize_db_columns_nullable_for_ddl(
        dialect_name=dialect_name,
        columns=columns,
        primary_key_cols=primary_key_cols,
        preserve_input_nullable=preserve_input_nullable,
    )


def _load_table_columns_for_resolution(
    *,
    engine: sa.Engine,
    table_name: str,
    schema_name: str | None,
) -> sa.Table:
    inspector = sa.inspect(engine)
    column_infos = inspector.get_columns(table_name, schema=schema_name)
    columns = [
        sa.Column(
            column_info["name"],
            column_info.get("type") or sa.NullType(),
            nullable=column_info.get("nullable", True),
        )
        for column_info in column_infos
    ]
    return sa.Table(table_name, sa.MetaData(), *columns, schema=schema_name)


def _create_table_from_schema_request(
    request: CreateTableFromSchemaRequest,
    engine: sa.Engine,
) -> CommonResponse:
    try:
        ensure_schema_exists(
            engine=engine,
            schema_name=request.schema_name,
        )

    except Exception as exc:
        detail = safe_exception_message(exc)
        raise CreateTableError(f"Failed to ensure schema exists: {detail}") from exc

    message = f"Table \"{request.table_name}\" created successfully."
    inspector = sa.inspect(engine)
    table_exists = inspector.has_table(request.table_name, schema=request.schema_name)

    if table_exists:
        match request.on_exists:
            case "error":
                raise CreateTableError(f"Table \"{request.table_name}\" already exists.")
            case "recreate":
                logger.info(f"Drop table name={request.table_name} before recreating.")
                table = sa.Table(
                    request.table_name,
                    sa.MetaData(),
                    schema=request.schema_name,
                    autoload_with=engine,
                )
                table.drop(engine, checkfirst=True)
                message = f"Table \"{request.table_name}\" recreated successfully."
            case "ignore":
                return CommonResponse(
                    success=True,
                    message=f"Table \"{request.table_name}\" already exists.",
                )

    try:
        normalized_columns = normalize_db_columns_nullable_for_ddl(
            dialect_name=engine.dialect.name,
            columns=list(request.columns),
            primary_key_cols=request.table_create_spec.primary_key_cols if request.table_create_spec else None,
            preserve_input_nullable=True,
        )
        create_typed_table_from_columns(
            engine=engine,
            table_name=request.table_name,
            columns=normalized_columns,
            schema_name=request.schema_name,
            spec=request.table_create_spec,
        )

    except Exception as exc:
        detail = safe_exception_message(exc)
        raise CreateTableError(f"Failed to create table from schema: {detail}") from exc

    logger.info(message)

    return CommonResponse(
        success=True,
        message=message,
    )


def _create_table_from_sql_request(
    request: CreateTableFromSQLRequest,
    engine: sa.Engine,
) -> CommonResponse:
    create_table_ddl = request.table_ddl.strip()
    if not create_table_ddl:
        raise CreateTableError("table_ddl must not be empty.")

    try:
        table_name, parsed_schema_name = validate_create_table_sql_target(
            create_table_ddl,
            engine=engine,
            expected_schema_name=request.schema_name,
        )
    except Exception as exc:
        detail = safe_exception_message(exc)
        raise CreateTableError(f"Failed to extract table and schema name from create_table_ddl: {detail}") from exc

    schema_name = parsed_schema_name or request.schema_name
    message = "Table created successfully from SQL."
    ensure_schema_exists(
        engine=engine,
        schema_name=schema_name,
    )

    if table_name:
        try:
            inspector = sa.inspect(engine)
            table_exists = inspector.has_table(table_name, schema=schema_name)
            if table_exists:
                match request.on_exists:
                    case "error":
                        raise CreateTableError(f"Table \"{table_name}\" already exists.")
                    case "recreate":
                        table = sa.Table(
                            table_name,
                            sa.MetaData(),
                            schema=schema_name,
                            autoload_with=engine,
                        )
                        table.drop(engine, checkfirst=True)
                        message = f"Table \"{table_name}\" recreated successfully from SQL."
                    case "ignore":
                        return CommonResponse(
                            success=True,
                            message=f"Table \"{table_name}\" already exists.",
                        )
        except Exception as exc:
            detail = safe_exception_message(exc)
            raise CreateTableError(f"Failed to check if table exists or drop existing table: {detail}") from exc
    elif request.on_exists in ("error", "ignore", "recreate"):
        logger.warning(
            "Unable to extract table name from create_table_sql; on_exists checks were skipped."
        )

    try:
        execute_raw_create_table_sql(
            engine=engine,
            create_table_sql=create_table_ddl,
            schema_name=request.schema_name,
            expected_schema_name=request.schema_name,
        )
    except Exception as exc:
        detail = safe_exception_message(exc)
        raise CreateTableError(f"Failed to execute create table: {detail}") from exc

    return CommonResponse(
        success=True,
        message=message,
    )


def create_table_from_connection_string(
    request: CreateTableRequest,
    connection_string: str,
) -> CommonResponse:
    try:
        engine = build_engine_from_connection_string(
            connection_string=connection_string,
            database_name=request.database_name,
        )
    except Exception as exc:
        detail = safe_exception_message(exc)
        raise CreateTableError(detail) from exc

    try:
        if request.mode == "from_schema":
            return _create_table_from_schema_request(request, engine)
        return _create_table_from_sql_request(request, engine)
    finally:
        engine.dispose()


def _resolve_write_columns_request(
    request: ResolveWriteColumnsRequest,
    connection_string: str,
) -> ResolveWriteColumnsResponse:
    try:
        engine = build_engine_from_connection_string(
            connection_string=connection_string,
            database_name=request.database_name,
            connect_timeout_sec=_RESOLVE_WRITE_COLUMNS_CONNECT_TIMEOUT_SEC,
        )
    except Exception as exc:
        detail = safe_exception_message(exc)
        raise ResolveWriteColumnsError(detail) from exc

    try:
        try:
            if request.mode == "typed_create":
                effective_database_name = (
                    request.database_name
                    or engine.url.database
                )
                result = resolve_typed_create_write_columns(
                    engine=engine,
                    dataframe_metadata=request.dataframe_metadata,
                    table_name=request.table_name,
                    database_name=effective_database_name,
                    schema_name=request.schema_name,
                    column_mapping=request.column_mapping,
                    table_create_spec=request.table_create_spec,
                )
            else:
                table = _load_table_columns_for_resolution(
                    engine=engine,
                    table_name=request.table_name,
                    schema_name=request.schema_name,
                )
                result = resolve_existing_table_write_columns(
                    table=table,
                    dataframe_metadata=request.dataframe_metadata,
                    column_mapping=request.column_mapping,
                    on_extra_df_columns=request.on_extra_df_columns,
                    on_missing_df_columns=request.on_missing_df_columns,
                )
        except Exception as exc:
            detail = safe_exception_message(exc)
            raise ResolveWriteColumnsError(f"Failed to resolve write columns: {detail}") from exc

        return ResolveWriteColumnsResponse.model_validate(result.model_dump())
    finally:
        engine.dispose()


async def _resolve_write_columns_request_async(
    request: ResolveWriteColumnsRequest,
    connection_string: str,
) -> ResolveWriteColumnsResponse:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                _resolve_write_columns_request,
                request,
                connection_string,
            ),
            timeout=_RESOLVE_WRITE_COLUMNS_REQUEST_TIMEOUT_SEC,
        )
    except TimeoutError as exc:
        raise ResolveWriteColumnsError(
            "Timed out while resolving write columns. Check database connectivity "
            "and try again."
        ) from exc


def _apply_table_column_actions_request(
    request: ApplyTableColumnActionsRequest,
    connection_string: str,
) -> ApplyTableColumnActionsResponse:
    try:
        engine = build_engine_from_connection_string(
            connection_string=connection_string,
            database_name=request.database_name,
        )
    except Exception as exc:
        detail = safe_exception_message(exc)
        raise ApplyTableColumnActionsError(detail) from exc

    effective_database_name = (
        request.database_name
        or engine.url.database
    )
    table_metadata = None
    try:
        applied_actions = apply_table_column_actions(
            engine=engine,
            table_name=request.table_name,
            schema_name=request.schema_name,
            database_name=effective_database_name,
            actions=request.actions,
            dry_run=request.dry_run,
        )
        if not request.dry_run:
            effective_schema_name = resolve_metadata_schema_for_ddl(
                dialect_name=engine.dialect.name,
                schema_name=request.schema_name,
                database_name=effective_database_name,
            )
            table_metadata = load_db_table_metadata(
                engine,
                table_name=request.table_name,
                schema_name=effective_schema_name,
                database_name=effective_database_name,
            )
    except Exception as exc:
        detail = safe_exception_message(exc)
        raise ApplyTableColumnActionsError(
            f"Failed to apply table column actions: {detail}"
        ) from exc

    finally:
        engine.dispose()

    sql = [statement for action in applied_actions for statement in action.sql]
    message = (
        "Table column actions generated successfully."
        if request.dry_run
        else "Table column actions applied successfully."
    )
    return ApplyTableColumnActionsResponse(
        success=True,
        message=message,
        sql=sql,
        applied_actions=applied_actions,
        table_metadata=table_metadata,
    )


def _effective_table_target(
    request: RecreateTableRequest | TruncateTableRequest,
    engine: sa.Engine,
) -> tuple[str | None, str | None]:
    database_name = (
        request.database_name
        or engine.url.database
    )
    schema_name = resolve_metadata_schema_for_ddl(
        dialect_name=engine.dialect.name,
        schema_name=request.schema_name,
        database_name=database_name,
    )
    return database_name, schema_name


def _recreate_table_request(
    request: RecreateTableRequest,
    connection_string: str,
) -> TableDDLActionResponse:
    try:
        engine = build_engine_from_connection_string(
            connection_string=connection_string,
            database_name=request.database_name,
        )
    except Exception as exc:
        raise RecreateTableError(safe_exception_message(exc)) from exc

    try:
        database_name, schema_name = _effective_table_target(request, engine)
        normalized_columns = normalize_db_columns_nullable_for_ddl(
            dialect_name=engine.dialect.name,
            columns=list(request.columns),
            primary_key_cols=(
                request.table_create_spec.primary_key_cols
                if request.table_create_spec
                else None
            ),
            preserve_input_nullable=True,
        )
        recreate_table_safely(
            engine=engine,
            table_name=request.table_name,
            columns=normalized_columns,
            schema_name=schema_name,
            spec=request.table_create_spec,
        )
        table_metadata = load_db_table_metadata(
            engine,
            table_name=request.table_name,
            schema_name=schema_name,
            database_name=database_name,
        )
    except Exception as exc:
        detail = safe_exception_message(exc)
        raise RecreateTableError(f"Failed to recreate table: {detail}") from exc
    finally:
        engine.dispose()

    return TableDDLActionResponse(
        message=f"Table {request.table_name!r} recreated successfully.",
        table_metadata=table_metadata,
    )


def _truncate_table_request(
    request: TruncateTableRequest,
    connection_string: str,
) -> TableDDLActionResponse:
    try:
        engine = build_engine_from_connection_string(
            connection_string=connection_string,
            database_name=request.database_name,
        )
    except Exception as exc:
        raise TruncateTableError(safe_exception_message(exc)) from exc

    try:
        database_name, schema_name = _effective_table_target(request, engine)
        if not sa.inspect(engine).has_table(request.table_name, schema=schema_name):
            qualified_name = (
                f"{schema_name}.{request.table_name}"
                if schema_name
                else request.table_name
            )
            raise ValueError(f"Table {qualified_name!r} does not exist.")

        dialect = resolve_dialect(engine)
        with engine.begin() as connection:
            connection.execute(
                sa.text(dialect.truncate_sql(request.table_name, schema_name))
            )

        table_metadata = load_db_table_metadata(
            engine,
            table_name=request.table_name,
            schema_name=schema_name,
            database_name=database_name,
        )
    except Exception as exc:
        detail = safe_exception_message(exc)
        raise TruncateTableError(f"Failed to truncate table: {detail}") from exc
    finally:
        engine.dispose()

    return TableDDLActionResponse(
        message=f"Table {request.table_name!r} truncated successfully.",
        table_metadata=table_metadata,
    )


def _generate_table_ddl_request(
    request: GenerateTableDDL,
    connection_string: str,
) -> GenerateTableDDLResponse:
    try:
        engine = build_engine_from_connection_string(
            connection_string=connection_string,
            database_name=request.database_name,
        )
    except Exception as exc:
        raise CreateTableError(safe_exception_message(exc)) from exc

    try:
        effective_database_name = request.database_name or engine.url.database
        if request.columns:
            sql = generate_create_table_ddl_from_columns(
                engine=engine,
                columns=list(request.columns),
                table_name=request.table_name,
                schema_name=request.schema_name,
                database_name=effective_database_name,
                table_create_spec=request.table_create_spec,
                preserve_input_nullable=True,
            )
        elif request.dataframe_metadata is not None:
            sql = generate_create_table_ddl_from_metadata(
                engine=engine,
                dataframe_metadata=request.dataframe_metadata,
                table_name=request.table_name,
                schema_name=request.schema_name,
                database_name=effective_database_name,
                index_col=request.index_col,
                table_create_spec=request.table_create_spec,
            )
        else:
            raise ValueError("Either columns or dataframe_metadata must be provided.")
    except Exception as exc:
        detail = safe_exception_message(exc)
        raise CreateTableError(f"Failed to generate table DDL: {detail}") from exc
    finally:
        engine.dispose()

    return GenerateTableDDLResponse(sql=sql)


@r.post("/create-table", response_model=CommonResponse)
async def create_table(
    request: CreateTableRequest,
    user: UserAccessOnly,
    redis: RedisBytes,
):
    connection = await resolve_ddl_connection(request.connection_id, user)
    response = await asyncio.to_thread(
        create_table_from_connection_string,
        request,
        connection.connection_string,
    )
    await invalidate_ddl_catalog(
        connection_id=connection.connection_id,
        user=user,
        redis=redis,
    )
    return response


@r.post("/resolve-write-columns", response_model=ResolveWriteColumnsResponse)
async def resolve_write_columns(
    request: ResolveWriteColumnsRequest,
    user: UserAccessOnly,
):
    connection = await resolve_ddl_connection(request.connection_id, user)
    return await _resolve_write_columns_request_async(
        request,
        connection.connection_string,
    )


@r.post("/apply-table-column-actions", response_model=ApplyTableColumnActionsResponse)
async def apply_column_actions(
    request: ApplyTableColumnActionsRequest,
    user: UserAccessOnly,
    redis: RedisBytes,
):
    connection = await resolve_ddl_connection(request.connection_id, user)
    response = await asyncio.to_thread(
        _apply_table_column_actions_request,
        request,
        connection.connection_string,
    )
    if not request.dry_run:
        await invalidate_ddl_catalog(
            connection_id=connection.connection_id,
            user=user,
            redis=redis,
        )
    return response


@r.post("/generate-table-ddl", response_model=GenerateTableDDLResponse)
async def generate_table_ddl(
    request: GenerateTableDDL,
    user: UserAccessOnly,
):
    connection = await resolve_ddl_connection(request.connection_id, user)
    return await asyncio.to_thread(
        _generate_table_ddl_request,
        request,
        connection.connection_string,
    )


@r.post("/recreate-table", response_model=TableDDLActionResponse)
async def recreate_table(
    request: RecreateTableRequest,
    user: UserAccessOnly,
    redis: RedisBytes,
):
    connection = await resolve_ddl_connection(request.connection_id, user)
    response = await asyncio.to_thread(
        _recreate_table_request,
        request,
        connection.connection_string,
    )
    await invalidate_ddl_catalog(
        connection_id=connection.connection_id,
        user=user,
        redis=redis,
    )
    return response


@r.post("/truncate-table", response_model=TableDDLActionResponse)
async def truncate_table(
    request: TruncateTableRequest,
    user: UserAccessOnly,
):
    connection = await resolve_ddl_connection(request.connection_id, user)
    return await asyncio.to_thread(
        _truncate_table_request,
        request,
        connection.connection_string,
    )
