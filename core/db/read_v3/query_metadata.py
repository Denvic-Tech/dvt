from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from importlib import import_module
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from core.db.read_v3.embedded_query import build_read_v3_query_embedding
from core.db.read_v3.sql_runner import resolve_sql_runner


def _normalize_type_repr(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, type):
        return value.__name__
    if hasattr(value, "name"):
        return str(getattr(value, "name"))
    return str(value)


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_numeric_type_repr(base: str, precision: object, scale: object) -> str:
    p = _safe_int(precision)
    s = _safe_int(scale)
    if p is None:
        return base
    if s is None:
        return f"{base}({p})"
    return f"{base}({p},{s})"


def _normalize_mssql_type_repr(type_code: object, precision: object, scale: object) -> str:
    if isinstance(type_code, type):
        if issubclass(type_code, bool):
            return "BIT"
        if issubclass(type_code, int):
            return "INT"
        if issubclass(type_code, float):
            return "FLOAT"
        if issubclass(type_code, Decimal):
            return _normalize_numeric_type_repr("DECIMAL", precision, scale)
        if issubclass(type_code, datetime):
            return "DATETIME"
        if issubclass(type_code, date):
            return "DATE"
        if issubclass(type_code, UUID):
            return "UNIQUEIDENTIFIER"
        if issubclass(type_code, str):
            return "NVARCHAR"
        if issubclass(type_code, (bytes, bytearray, memoryview)):
            return "VARBINARY"
    return ""


def _normalize_oracle_type_repr(type_code: object, precision: object, scale: object) -> str:
    raw = _normalize_type_repr(type_code).upper()
    if "DB_TYPE_NUMBER" in raw or raw == "NUMBER":
        return _normalize_numeric_type_repr("NUMBER", precision, scale)
    if "DB_TYPE_TIMESTAMP" in raw or "TIMESTAMP" in raw:
        return "TIMESTAMP"
    if "DB_TYPE_DATE" in raw or raw == "DATE":
        return "DATE"
    if "DB_TYPE_BINARY_DOUBLE" in raw:
        return "BINARY_DOUBLE"
    if "DB_TYPE_BINARY_FLOAT" in raw:
        return "BINARY_FLOAT"
    if "DB_TYPE_CHAR" in raw:
        return "CHAR"
    if "DB_TYPE_VARCHAR" in raw:
        return "VARCHAR2"
    if "DB_TYPE_NCHAR" in raw:
        return "NCHAR"
    if "DB_TYPE_NVARCHAR" in raw:
        return "NVARCHAR2"
    if "DB_TYPE_CLOB" in raw:
        return "CLOB"
    return raw


def _lookup_mysql_field_type_name(type_code: int) -> str:
    modules = (
        "pymysql.constants.FIELD_TYPE",
        "MySQLdb.constants.FIELD_TYPE",
    )
    for module_name in modules:
        try:
            module = import_module(module_name)
        except Exception:
            continue
        for key, value in vars(module).items():
            if isinstance(value, int) and value == type_code:
                return key

    try:
        field_type = import_module("mysql.connector.constants").FieldType
        return str(field_type.get_info(type_code))
    except Exception:
        return str(type_code)


def _normalize_mysql_type_name(type_name: str) -> str:
    normalized = (type_name or "").strip().upper()
    aliases = {
        "LONG": "INT",
        "LONGLONG": "BIGINT",
        "SHORT": "SMALLINT",
        "TINY": "TINYINT",
        "NEWDECIMAL": "DECIMAL",
        "VAR_STRING": "VARCHAR",
        "STRING": "CHAR",
    }
    return aliases.get(normalized, normalized)


def describe_mssql_table_column_types(
    engine: Engine,
    *,
    table_name: str,
    schema: str | None,
) -> dict[str, str]:
    dialect_name = (engine.dialect.name or "").lower()
    if "mssql" not in dialect_name and "sqlserver" not in dialect_name:
        return {}

    sql = text(
        """
        SELECT
            columns.name AS column_name,
            CASE
                WHEN declared_types.is_user_defined = 1
                     AND declared_types.is_assembly_type = 0
                THEN TYPE_NAME(columns.system_type_id)
                ELSE declared_types.name
            END AS type_name
        FROM sys.columns AS columns
        JOIN sys.tables AS tables
            ON tables.object_id = columns.object_id
        JOIN sys.schemas AS schemas
            ON schemas.schema_id = tables.schema_id
        JOIN sys.types AS declared_types
            ON declared_types.user_type_id = columns.user_type_id
        WHERE tables.name = :table_name
          AND schemas.name = COALESCE(:schema_name, SCHEMA_NAME())
        """
    )
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                sql,
                {"table_name": table_name, "schema_name": schema},
            ).all()
    except Exception:
        return {}

    return {
        str(row.column_name).lower(): str(row.type_name)
        for row in rows
        if row.column_name is not None and row.type_name is not None
    }


def describe_query_columns(engine: Engine, raw_query: str) -> list[tuple[str, str]]:
    dialect_name = (engine.dialect.name or "").lower()

    try:
        if "clickhouse" in dialect_name:
            return resolve_sql_runner(engine).describe_query_columns(raw_query)

        if "postgres" in dialect_name:
            sql = f"SELECT * FROM ({raw_query}) AS t LIMIT 0"
            conn = engine.raw_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT oid, typname FROM pg_type")
                type_map = {int(oid): str(name) for oid, name in cursor.fetchall()}
                cursor.execute(sql)
                result: list[tuple[str, str]] = []
                for col in cursor.description:
                    name = str(getattr(col, "name", col[0]))
                    type_code = getattr(col, "type_code", col[1] if len(col) > 1 else None)
                    resolved = type_map.get(int(type_code), _normalize_type_repr(type_code))
                    result.append((name, resolved))
                return result
            finally:
                cursor.close()
                conn.close()

        if "mssql" in dialect_name or "sqlserver" in dialect_name:
            query_embedding = build_read_v3_query_embedding(raw_query, dialect_name=dialect_name)
            sql = f"{query_embedding.cte_prefix_sql} SELECT TOP 0 * {query_embedding.relation_sql}"
            conn = engine.raw_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT system_type_id, name FROM sys.types WHERE user_type_id = system_type_id")
                type_map = {int(type_id): str(name) for type_id, name in cursor.fetchall()}
                cursor.execute(sql)
                result: list[tuple[str, str]] = []
                for col in cursor.description:
                    name = str(col[0])
                    type_code = col[1] if len(col) > 1 else None
                    precision = col[4] if len(col) > 4 else None
                    scale = col[5] if len(col) > 5 else None
                    resolved = ""
                    type_id = _safe_int(type_code)
                    if type_id is not None:
                        resolved = type_map.get(type_id, "")
                    if not resolved:
                        resolved = _normalize_mssql_type_repr(type_code, precision, scale)
                    if not resolved:
                        resolved = _normalize_type_repr(type_code)
                    result.append((name, resolved))
                return result
            finally:
                cursor.close()
                conn.close()

        if "oracle" in dialect_name:
            sql = f"SELECT * FROM ({raw_query}) t WHERE 1=0"
            conn = engine.raw_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(sql)
                result: list[tuple[str, str]] = []
                for col in cursor.description:
                    type_code = col[1] if len(col) > 1 else None
                    precision = col[4] if len(col) > 4 else None
                    scale = col[5] if len(col) > 5 else None
                    result.append(
                        (
                            str(col[0]),
                            _normalize_oracle_type_repr(type_code, precision, scale),
                        )
                    )
                return result
            finally:
                cursor.close()
                conn.close()

        if "mysql" in dialect_name or "mariadb" in dialect_name:
            sql = f"SELECT * FROM ({raw_query}) AS t LIMIT 0"
            conn = engine.raw_connection()
            cursor = conn.cursor()
            try:
                cursor.execute(sql)
                result: list[tuple[str, str]] = []
                for col in cursor.description:
                    name = str(col[0])
                    type_code = col[1] if len(col) > 1 else None
                    if type_code is None:
                        resolved = ""
                    else:
                        try:
                            resolved = _normalize_mysql_type_name(
                                _lookup_mysql_field_type_name(int(type_code))
                            )
                        except (TypeError, ValueError):
                            resolved = _normalize_type_repr(type_code)
                    result.append((name, resolved))
                return result
            finally:
                cursor.close()
                conn.close()
    except Exception:
        return []

    return []
