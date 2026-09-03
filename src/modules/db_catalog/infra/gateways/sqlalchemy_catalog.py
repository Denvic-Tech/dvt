from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import date, datetime, time as time_value, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.pool import NullPool

from core.metadata import load_db_table_metadata
from core.types import DataType

from src.modules.db_catalog.domain import (
    AuthorizedCatalogConnection,
    CatalogColumn,
    CatalogDatabase,
    CatalogOperation,
    CatalogPreviewTooLargeError,
    CatalogPreviewValue,
    CatalogRequest,
    CatalogRequestValidationError,
    CatalogResult,
    CatalogSchema,
    CatalogSourceTimeoutError,
    CatalogSourceUnavailableError,
    CatalogTableDetails,
    CatalogTableKind,
    CatalogTableNotFoundError,
    CatalogTablePreview,
    CatalogTablePreviewColumn,
    CatalogTablePreviewRequest,
    CatalogTableSummary,
)
from src.modules.db_catalog.domain.gateways import CatalogSourceGateway, TablePreviewSourceGateway
from src.modules.db_catalog.domain.policies import decode_cursor, encode_cursor

TABLE_PREVIEW_ROW_LIMIT = 50


def _clip_preview_text(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    if max_chars == 1:
        return "…", True
    return f"{value[: max_chars - 1]}…", True


def _normalize_preview_value(  # noqa: PLR0911
    value: object,
    max_chars: int,
) -> tuple[CatalogPreviewValue, bool]:
    if value is None or isinstance(value, (bool, int)):
        return value, False
    if isinstance(value, float):
        return (value, False) if math.isfinite(value) else (str(value), False)
    if isinstance(value, str):
        return _clip_preview_text(value, max_chars)
    if isinstance(value, (bytes, bytearray, memoryview)):
        placeholder = f"<binary:{len(value)} bytes>"
        clipped, _ = _clip_preview_text(placeholder, max_chars)
        return clipped, True
    if isinstance(value, (datetime, date, time_value)):
        return _clip_preview_text(value.isoformat(), max_chars)
    if isinstance(value, (Decimal, UUID, timedelta)):
        return _clip_preview_text(str(value), max_chars)

    try:
        if isinstance(value, (dict, list, tuple)):
            text = json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))
        else:
            text = str(value)
    except (TypeError, ValueError):
        text = repr(value)
    return _clip_preview_text(text, max_chars)


def _preview_payload_size(preview: CatalogTablePreview) -> int:
    payload = {
        "columns": [{"name": column.name, "dtype": column.dtype} for column in preview.columns],
        "rows": [list(row) for row in preview.rows],
        "truncated": preview.truncated,
    }
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


class SQLAlchemyCatalogSource(CatalogSourceGateway, TablePreviewSourceGateway):
    def __init__(
        self,
        *,
        connect_timeout_seconds: int,
        query_timeout_seconds: int,
        request_timeout_seconds: int,
        max_concurrency: int,
        preview_cell_max_chars: int = 4096,
        preview_max_response_bytes: int = 1024 * 1024,
    ) -> None:
        self._connect_timeout_seconds = connect_timeout_seconds
        self._query_timeout_seconds = query_timeout_seconds
        self._request_timeout_seconds = request_timeout_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._preview_cell_max_chars = preview_cell_max_chars
        self._preview_max_response_bytes = preview_max_response_bytes

    async def fetch(
        self,
        connection: AuthorizedCatalogConnection,
        request: CatalogRequest,
    ) -> CatalogResult:
        async with self._semaphore:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._fetch_sync, connection, request),
                    timeout=self._request_timeout_seconds,
                )
            except TimeoutError as exc:
                raise CatalogSourceTimeoutError("DB catalog request timed out.") from exc

    async def fetch_preview(
        self,
        connection: AuthorizedCatalogConnection,
        request: CatalogTablePreviewRequest,
    ) -> CatalogTablePreview:
        async with self._semaphore:
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(self._fetch_preview_sync, connection, request),
                    timeout=self._request_timeout_seconds,
                )
            except TimeoutError as exc:
                raise CatalogSourceTimeoutError("DB table preview request timed out.") from exc

    def _fetch_sync(
        self,
        connection: AuthorizedCatalogConnection,
        request: CatalogRequest,
    ) -> CatalogResult:
        engine: sa.Engine | None = None
        try:
            engine = self._create_engine(connection, request.database_name)
            if request.operation == CatalogOperation.TABLE:
                return self._fetch_table(engine, connection, request)
            return self._fetch_page(engine, connection, request)
        except (CatalogRequestValidationError, CatalogTableNotFoundError):
            raise
        except sa.exc.TimeoutError as exc:
            raise CatalogSourceTimeoutError("DB catalog query timed out.") from exc
        except sa.exc.DBAPIError as exc:
            error_name = type(exc.orig).__name__.lower() if exc.orig is not None else ""
            error_text = str(exc.orig).lower() if exc.orig is not None else ""
            if (
                "timeout" in error_name
                or "timed out" in error_text
                or "statement timeout" in error_text
            ):
                raise CatalogSourceTimeoutError("DB catalog query timed out.") from None
            raise CatalogSourceUnavailableError("DB catalog source query failed.") from None
        except (OSError, TypeError, ValueError) as exc:
            raise CatalogSourceUnavailableError("DB catalog source is unavailable.") from exc
        finally:
            if engine is not None:
                engine.dispose()

    def _fetch_preview_sync(
        self,
        connection: AuthorizedCatalogConnection,
        request: CatalogTablePreviewRequest,
    ) -> CatalogTablePreview:
        engine: sa.Engine | None = None
        try:
            engine = self._create_engine(connection, request.database_name)
            return self._fetch_preview(engine, connection, request)
        except (CatalogPreviewTooLargeError, CatalogTableNotFoundError):
            raise
        except sa.exc.NoSuchTableError as exc:
            raise CatalogTableNotFoundError("DB catalog table was not found.") from exc
        except sa.exc.TimeoutError as exc:
            raise CatalogSourceTimeoutError("DB table preview query timed out.") from exc
        except sa.exc.DBAPIError as exc:
            error_name = type(exc.orig).__name__.lower() if exc.orig is not None else ""
            error_text = str(exc.orig).lower() if exc.orig is not None else ""
            if (
                "timeout" in error_name
                or "timed out" in error_text
                or "statement timeout" in error_text
            ):
                raise CatalogSourceTimeoutError("DB table preview query timed out.") from None
            raise CatalogSourceUnavailableError("DB table preview query failed.") from None
        except (OSError, TypeError, ValueError) as exc:
            raise CatalogSourceUnavailableError("DB table preview source is unavailable.") from exc
        finally:
            if engine is not None:
                engine.dispose()

    def _create_engine(
        self,
        connection: AuthorizedCatalogConnection,
        requested_database: str | None,
    ) -> sa.Engine:
        url = sa.make_url(connection.connection_url)
        dialect = connection.dialect
        if requested_database:
            if dialect in {"postgresql", "mysql", "mariadb", "mssql", "sqlserver", "clickhouse"}:
                url = url.set(database=requested_database)
            elif requested_database != connection.configured_database:
                raise CatalogRequestValidationError(
                    f"Database override is not supported for {dialect}."
                )

        driver = url.drivername.split("+", 1)[1] if "+" in url.drivername else ""
        connect_args: dict[str, Any] = {}
        if dialect == "postgresql" and driver in {"psycopg", "psycopg2", ""}:
            connect_args["connect_timeout"] = self._connect_timeout_seconds
        elif dialect in {"mysql", "mariadb"} and driver in {"pymysql", "mysqldb", ""}:
            connect_args["connect_timeout"] = self._connect_timeout_seconds
            if driver == "pymysql":
                connect_args["read_timeout"] = self._query_timeout_seconds
        elif (
            dialect in {"mssql", "sqlserver"} and driver in {"pyodbc", ""}
        ) or dialect == "sqlite":
            connect_args["timeout"] = self._connect_timeout_seconds
        elif dialect == "clickhouse":
            connect_args.update(
                connect_timeout=self._connect_timeout_seconds,
                send_receive_timeout=self._query_timeout_seconds,
            )
        elif dialect == "oracle" and driver in {"oracledb", ""}:
            connect_args["tcp_connect_timeout"] = self._connect_timeout_seconds

        engine = sa.create_engine(url, poolclass=NullPool, connect_args=connect_args)
        self._install_driver_deadlines(engine, dialect)
        return engine

    def _fetch_preview(
        self,
        engine: sa.Engine,
        connection: AuthorizedCatalogConnection,
        request: CatalogTablePreviewRequest,
    ) -> CatalogTablePreview:
        table = sa.Table(
            request.table_name,
            sa.MetaData(),
            schema=request.schema_name,
            autoload_with=engine,
        )
        columns = tuple(
            CatalogTablePreviewColumn(
                name=column.name,
                dtype=DataType.from_type(str(column.type)).value,
            )
            for column in table.columns
        )
        statement = self._build_preview_statement(table)
        with engine.connect() as db_connection:
            self._apply_session_deadline(db_connection, connection.dialect)
            raw_rows = db_connection.execute(statement).fetchmany(TABLE_PREVIEW_ROW_LIMIT + 1)

        has_more_rows = len(raw_rows) > TABLE_PREVIEW_ROW_LIMIT
        preview = CatalogTablePreview(columns=columns, rows=(), truncated=has_more_rows)
        if _preview_payload_size(preview) > self._preview_max_response_bytes:
            raise CatalogPreviewTooLargeError("DB table preview columns exceed the size limit.")

        rows: list[tuple[CatalogPreviewValue, ...]] = []
        truncated = has_more_rows
        for raw_row in raw_rows[:TABLE_PREVIEW_ROW_LIMIT]:
            normalized_values: list[CatalogPreviewValue] = []
            row_truncated = False
            for value in raw_row:
                normalized, value_truncated = _normalize_preview_value(
                    value,
                    self._preview_cell_max_chars,
                )
                normalized_values.append(normalized)
                row_truncated = row_truncated or value_truncated

            candidate_rows = (*rows, tuple(normalized_values))
            candidate = CatalogTablePreview(
                columns=columns,
                rows=candidate_rows,
                truncated=truncated or row_truncated,
            )
            if _preview_payload_size(candidate) > self._preview_max_response_bytes:
                truncated = True
                break
            rows.append(tuple(normalized_values))
            truncated = truncated or row_truncated

        return CatalogTablePreview(
            columns=columns,
            rows=tuple(rows),
            truncated=truncated,
        )

    @staticmethod
    def _build_preview_statement(table: sa.Table) -> sa.Select:
        return sa.select(table).limit(TABLE_PREVIEW_ROW_LIMIT + 1)

    def _install_driver_deadlines(self, engine: sa.Engine, dialect: str) -> None:
        query_timeout = self._query_timeout_seconds
        if dialect == "postgresql":

            @sa.event.listens_for(engine, "connect")
            def _set_postgresql_timeout(dbapi_connection, _record):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute(f"SET statement_timeout = {query_timeout * 1000}")
                finally:
                    cursor.close()
        elif dialect in {"mysql", "mariadb"}:

            @sa.event.listens_for(engine, "connect")
            def _set_mysql_timeout(dbapi_connection, _record):
                cursor = dbapi_connection.cursor()
                try:
                    if dialect == "mariadb":
                        cursor.execute(f"SET SESSION max_statement_time = {query_timeout}")
                    else:
                        cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {query_timeout * 1000}")
                finally:
                    cursor.close()
        elif dialect in {"mssql", "sqlserver"}:

            @sa.event.listens_for(engine, "before_cursor_execute")
            def _set_cursor_timeout(_conn, cursor, _statement, _parameters, _context, _many):
                if hasattr(cursor, "timeout"):
                    cursor.timeout = query_timeout
        elif dialect == "oracle":

            @sa.event.listens_for(engine, "connect")
            def _set_oracle_timeout(dbapi_connection, _record):
                if hasattr(dbapi_connection, "call_timeout"):
                    dbapi_connection.call_timeout = query_timeout * 1000
        elif dialect == "sqlite":

            @sa.event.listens_for(engine, "connect")
            def _set_sqlite_timeout(dbapi_connection, _record):
                deadline = time.monotonic() + query_timeout
                dbapi_connection.set_progress_handler(
                    lambda: int(time.monotonic() >= deadline),
                    1000,
                )
        elif dialect == "clickhouse":

            @sa.event.listens_for(engine, "connect")
            def _set_clickhouse_timeout(dbapi_connection, _record):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute(f"SET max_execution_time = {query_timeout}")
                finally:
                    cursor.close()

    def _fetch_page(
        self,
        engine: sa.Engine,
        connection: AuthorizedCatalogConnection,
        request: CatalogRequest,
    ) -> CatalogResult:
        statement, params = self._build_page_query(connection, request)
        with engine.connect() as db_connection:
            self._apply_session_deadline(db_connection, connection.dialect)
            rows = list(db_connection.execute(sa.text(statement), params).mappings())

        has_more = len(rows) > request.limit
        rows = rows[: request.limit]
        next_cursor = None
        if has_more and rows:
            last_name = str(rows[-1]["name"])
            next_cursor = encode_cursor(last_name.casefold(), last_name)

        if request.operation == CatalogOperation.DATABASES:
            items = tuple(
                CatalogDatabase(
                    name=str(row["name"]),
                    is_current=str(row["name"]) == connection.configured_database,
                )
                for row in rows
            )
        elif request.operation == CatalogOperation.SCHEMAS:
            items = tuple(
                CatalogSchema(
                    name=str(row["name"]),
                    database_name=request.database_name or connection.configured_database,
                )
                for row in rows
            )
        else:
            items = tuple(
                CatalogTableSummary(
                    name=str(row["name"]),
                    kind=self._normalize_kind(row.get("kind")),
                    database_name=request.database_name or connection.configured_database,
                    schema_name=request.schema_name,
                )
                for row in rows
            )
        return CatalogResult(items=items, next_cursor=next_cursor)

    def _fetch_table(
        self,
        engine: sa.Engine,
        connection: AuthorizedCatalogConnection,
        request: CatalogRequest,
    ) -> CatalogResult:
        kind = self._fetch_exact_kind(engine, connection, request)
        try:
            table = load_db_table_metadata(
                engine,
                table_name=request.table_name or "",
                schema_name=request.schema_name,
                database_name=request.database_name or connection.configured_database,
            )
        except ValueError as exc:
            raise CatalogTableNotFoundError("DB catalog table was not found.") from exc

        columns = tuple(
            CatalogColumn(
                name=column.name,
                ordinal=ordinal,
                dtype=str(column.dtype),
                nullable=column.nullable,
                indexed=bool(column.index),
                primary_key=bool(column.primary_key),
                indexes=tuple(column.indexes or ()),
            )
            for ordinal, column in enumerate(table.columns, start=1)
        )
        return CatalogResult(
            table=CatalogTableDetails(
                name=table.name,
                kind=kind,
                columns=columns,
                database_name=request.database_name or connection.configured_database,
                schema_name=request.schema_name,
            )
        )

    def _fetch_exact_kind(
        self,
        engine: sa.Engine,
        connection: AuthorizedCatalogConnection,
        request: CatalogRequest,
    ) -> CatalogTableKind:
        statement, params = self._build_exact_table_query(connection, request)
        with engine.connect() as db_connection:
            self._apply_session_deadline(db_connection, connection.dialect)
            row = db_connection.execute(sa.text(statement), params).mappings().first()
        if row is None:
            raise CatalogTableNotFoundError("DB catalog table was not found.")
        return self._normalize_kind(row.get("kind"))

    def _apply_session_deadline(self, connection: sa.Connection, dialect: str) -> None:
        milliseconds = self._query_timeout_seconds * 1000
        if dialect == "postgresql":
            connection.exec_driver_sql(f"SET statement_timeout = {milliseconds}")
        elif dialect == "clickhouse":
            connection.exec_driver_sql(f"SET max_execution_time = {self._query_timeout_seconds}")

    def _build_page_query(
        self,
        connection: AuthorizedCatalogConnection,
        request: CatalogRequest,
    ) -> tuple[str, dict[str, Any]]:
        dialect = connection.dialect
        cursor = decode_cursor(request.cursor)
        params: dict[str, Any] = {
            "search": self._search_pattern(request.search),
            "cursor_norm": cursor[0] if cursor else None,
            "cursor_exact": cursor[1] if cursor else None,
            "row_limit": request.limit + 1,
            "database": request.database_name or connection.configured_database,
            "schema": request.schema_name,
            "include_table": CatalogTableKind.TABLE in request.kinds,
            "include_view": CatalogTableKind.VIEW in request.kinds,
        }
        filters = (
            self._postgresql_name_filters("{name}")
            if dialect == "postgresql"
            else self._name_filters("{name}")
        )

        if dialect == "postgresql":
            if request.operation == CatalogOperation.DATABASES:
                name = "datname"
                statement = f"""
                    SELECT {name} AS name
                    FROM pg_database
                    WHERE datallowconn AND NOT datistemplate
                      AND has_database_privilege({name}, 'CONNECT')
                      AND {name} NOT IN ('template0', 'template1')
                      {filters.format(name=name)}
                    ORDER BY LOWER({name}), {name}
                    LIMIT :row_limit
                """
            elif request.operation == CatalogOperation.SCHEMAS:
                name = "schema_name"
                statement = f"""
                    SELECT {name} AS name
                    FROM information_schema.schemata
                    WHERE {name} NOT IN ('information_schema', 'pg_catalog')
                      AND {name} NOT LIKE 'pg_toast%'
                      AND {name} NOT LIKE 'pg_temp_%'
                      {filters.format(name=name)}
                    ORDER BY LOWER({name}), {name}
                    LIMIT :row_limit
                """
            else:
                name = "table_name"
                statement = f"""
                    SELECT {name} AS name, table_type AS kind
                    FROM information_schema.tables
                    WHERE table_schema = COALESCE(:schema, current_schema())
                      AND ((:include_table AND table_type = 'BASE TABLE')
                           OR (:include_view AND table_type = 'VIEW'))
                      {filters.format(name=name)}
                    ORDER BY LOWER({name}), {name}
                    LIMIT :row_limit
                """
            return statement, params

        if dialect in {"mysql", "mariadb"}:
            if request.operation == CatalogOperation.DATABASES:
                name = "schema_name"
                statement = f"""
                    SELECT {name} AS name
                    FROM information_schema.schemata
                    WHERE {name} NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
                      {filters.format(name=name)}
                    ORDER BY LOWER({name}), {name}
                    LIMIT :row_limit
                """
            else:
                name = "table_name"
                statement = f"""
                    SELECT {name} AS name, table_type AS kind
                    FROM information_schema.tables
                    WHERE table_schema = :database
                      AND ((:include_table AND table_type = 'BASE TABLE')
                           OR (:include_view AND table_type = 'VIEW'))
                      {filters.format(name=name)}
                    ORDER BY LOWER({name}), {name}
                    LIMIT :row_limit
                """
            return statement, params

        if dialect in {"mssql", "sqlserver"}:
            limit = request.limit + 1
            if request.operation == CatalogOperation.DATABASES:
                name = "name"
                statement = f"""
                    SELECT TOP ({limit}) {name} AS name
                    FROM sys.databases
                    WHERE database_id > 4 AND state = 0 AND HAS_DBACCESS({name}) = 1
                      {filters.format(name=name)}
                    ORDER BY LOWER({name}), {name}
                """
            elif request.operation == CatalogOperation.SCHEMAS:
                name = "name"
                statement = f"""
                    SELECT TOP ({limit}) {name} AS name
                    FROM sys.schemas
                    WHERE {name} NOT IN ('sys', 'INFORMATION_SCHEMA', 'guest')
                      {filters.format(name=name)}
                    ORDER BY LOWER({name}), {name}
                """
            else:
                name = "o.name"
                statement = f"""
                    SELECT TOP ({limit}) {name} AS name,
                           CASE WHEN o.type = 'V' THEN 'VIEW' ELSE 'BASE TABLE' END AS kind
                    FROM sys.objects o
                    JOIN sys.schemas s ON s.schema_id = o.schema_id
                    WHERE s.name = COALESCE(:schema, SCHEMA_NAME())
                      AND ((:include_table = 1 AND o.type = 'U')
                           OR (:include_view = 1 AND o.type = 'V'))
                      {filters.format(name=name)}
                    ORDER BY LOWER({name}), {name}
                """
            return statement, params

        if dialect == "clickhouse":
            params["search_plain"] = request.search or ""
            filters_ch = self._clickhouse_name_filters("{name}")
            if request.operation == CatalogOperation.DATABASES:
                name = "name"
                statement = f"""
                    SELECT {name} AS name
                    FROM system.databases
                    WHERE {name} NOT IN ('system', 'information_schema', 'INFORMATION_SCHEMA')
                      {filters_ch.format(name=name)}
                    ORDER BY lowerUTF8({name}), {name}
                    LIMIT :row_limit
                """
            else:
                name = "name"
                statement = f"""
                    SELECT {name} AS name,
                           if(engine = 'View' OR engine = 'MaterializedView', 'VIEW', 'BASE TABLE') AS kind
                    FROM system.tables
                    WHERE database = :database
                      AND ((:include_table AND engine NOT IN ('View', 'MaterializedView'))
                           OR (:include_view AND engine IN ('View', 'MaterializedView')))
                      {filters_ch.format(name=name)}
                    ORDER BY lowerUTF8({name}), {name}
                    LIMIT :row_limit
                """
            return statement, params

        if dialect == "oracle":
            limit = request.limit + 1
            if request.operation == CatalogOperation.SCHEMAS:
                name = "USER"
                statement = f"""
                    SELECT {name} AS name FROM dual
                    WHERE 1 = 1 {filters.format(name=name)}
                    FETCH FIRST {limit} ROWS ONLY
                """
            else:
                name = "object_name"
                statement = f"""
                    SELECT {name} AS name, object_type AS kind
                    FROM user_objects
                    WHERE ((:include_table = 1 AND object_type = 'TABLE')
                           OR (:include_view = 1 AND object_type = 'VIEW'))
                      {filters.format(name=name)}
                    ORDER BY LOWER({name}), {name}
                    FETCH FIRST {limit} ROWS ONLY
                """
            return statement, params

        if dialect == "sqlite":
            if request.operation == CatalogOperation.SCHEMAS:
                name = "name"
                statement = f"""
                    SELECT {name} AS name FROM pragma_database_list
                    WHERE {name} IN ('main', 'temp')
                      {filters.format(name=name)}
                    ORDER BY LOWER({name}), {name}
                    LIMIT :row_limit
                """
            else:
                schema = request.schema_name or "main"
                if schema not in {"main", "temp"}:
                    raise CatalogRequestValidationError("SQLite schema must be main or temp.")
                name = "name"
                statement = f"""
                    SELECT {name} AS name,
                           CASE WHEN type = 'view' THEN 'VIEW' ELSE 'BASE TABLE' END AS kind
                    FROM {schema}.sqlite_master
                    WHERE {name} NOT LIKE 'sqlite_%'
                      AND ((:include_table AND type = 'table') OR (:include_view AND type = 'view'))
                      {filters.format(name=name)}
                    ORDER BY LOWER({name}), {name}
                    LIMIT :row_limit
                """
            return statement, params

        raise CatalogSourceUnavailableError("Unsupported DB catalog dialect.")

    def _build_exact_table_query(
        self,
        connection: AuthorizedCatalogConnection,
        request: CatalogRequest,
    ) -> tuple[str, dict[str, Any]]:
        dialect = connection.dialect
        params = {
            "name": request.table_name,
            "schema": request.schema_name,
            "database": request.database_name or connection.configured_database,
        }
        if dialect == "postgresql":
            return (
                """
                SELECT table_type AS kind FROM information_schema.tables
                WHERE table_schema = COALESCE(:schema, current_schema()) AND table_name = :name
            """,
                params,
            )
        if dialect in {"mysql", "mariadb"}:
            return (
                """
                SELECT table_type AS kind FROM information_schema.tables
                WHERE table_schema = :database AND table_name = :name
            """,
                params,
            )
        if dialect in {"mssql", "sqlserver"}:
            return (
                """
                SELECT CASE WHEN o.type = 'V' THEN 'VIEW' ELSE 'BASE TABLE' END AS kind
                FROM sys.objects o JOIN sys.schemas s ON s.schema_id = o.schema_id
                WHERE s.name = COALESCE(:schema, SCHEMA_NAME())
                  AND o.name = :name AND o.type IN ('U', 'V')
            """,
                params,
            )
        if dialect == "clickhouse":
            return (
                """
                SELECT if(engine = 'View' OR engine = 'MaterializedView', 'VIEW', 'BASE TABLE') AS kind
                FROM system.tables WHERE database = :database AND name = :name
            """,
                params,
            )
        if dialect == "oracle":
            return (
                """
                SELECT object_type AS kind FROM user_objects
                WHERE object_name = :name AND object_type IN ('TABLE', 'VIEW')
            """,
                params,
            )
        if dialect == "sqlite":
            schema = request.schema_name or "main"
            if schema not in {"main", "temp"}:
                raise CatalogRequestValidationError("SQLite schema must be main or temp.")
            return (
                f"""
                SELECT CASE WHEN type = 'view' THEN 'VIEW' ELSE 'BASE TABLE' END AS kind
                FROM {schema}.sqlite_master WHERE name = :name AND type IN ('table', 'view')
            """,
                params,
            )
        raise CatalogSourceUnavailableError("Unsupported DB catalog dialect.")

    @staticmethod
    def _name_filters(name_expression: str) -> str:
        return f"""
            AND (:search IS NULL OR LOWER({name_expression}) LIKE :search ESCAPE '!')
            AND (
                :cursor_norm IS NULL
                OR LOWER({name_expression}) > :cursor_norm
                OR (LOWER({name_expression}) = :cursor_norm AND {name_expression} > :cursor_exact)
            )
        """

    @staticmethod
    def _postgresql_name_filters(name_expression: str) -> str:
        return f"""
            AND (
                CAST(:search AS TEXT) IS NULL
                OR LOWER({name_expression}) LIKE CAST(:search AS TEXT) ESCAPE '!'
            )
            AND (
                CAST(:cursor_norm AS TEXT) IS NULL
                OR LOWER({name_expression}) > CAST(:cursor_norm AS TEXT)
                OR (
                    LOWER({name_expression}) = CAST(:cursor_norm AS TEXT)
                    AND {name_expression} > CAST(:cursor_exact AS TEXT)
                )
            )
        """

    @staticmethod
    def _clickhouse_name_filters(name_expression: str) -> str:
        return f"""
            AND (:search_plain = '' OR positionCaseInsensitiveUTF8({name_expression}, :search_plain) > 0)
            AND (
                :cursor_norm IS NULL
                OR lowerUTF8({name_expression}) > :cursor_norm
                OR (lowerUTF8({name_expression}) = :cursor_norm AND {name_expression} > :cursor_exact)
            )
        """

    @staticmethod
    def _search_pattern(search: str | None) -> str | None:
        if not search:
            return None
        escaped = search.casefold().replace("!", "!!").replace("%", "!%").replace("_", "!_")
        return f"%{escaped}%"

    @staticmethod
    def _normalize_kind(value: object) -> CatalogTableKind:
        normalized = str(value or "").upper().replace("_", " ")
        return CatalogTableKind.VIEW if "VIEW" in normalized else CatalogTableKind.TABLE
