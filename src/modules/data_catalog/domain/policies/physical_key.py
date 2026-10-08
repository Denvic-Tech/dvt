"""Нормализация локатора в ключ физической базы."""

from __future__ import annotations

from ..catalog_values import PhysicalLocator, RawLocator
from ..graph import ConnectionLocator

_CANONICAL_DIALECTS: dict[str, str] = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "mysql": "mysql",
    "mariadb": "mysql",
    "clickhouse": "clickhouse",
    "mssql": "mssql",
    "sqlserver": "mssql",
    "oracle": "oracle",
    "mongodb": "mongodb",
    "sqlite": "sqlite",
}

_DEFAULT_SCHEMAS: dict[str, str] = {
    "postgresql": "public",
    "mssql": "dbo",
}

_DIALECTS_WITHOUT_SCHEMAS = frozenset({"mysql", "clickhouse", "sqlite", "mongodb"})


def canonical_dialect(connection_type: str | None) -> str | None:
    if not connection_type:
        return None
    return _CANONICAL_DIALECTS.get(connection_type.strip().lower())


def supports_schemas(dialect: str) -> bool:
    return dialect not in _DIALECTS_WITHOUT_SCHEMAS


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().strip('"').strip("`").strip("[]")
    return cleaned or None


def normalize_locator(raw: RawLocator, connection: ConnectionLocator, *, dialect: str) -> PhysicalLocator:
    """Дополняет локатор ноды координатами connection'а и дефолтами диалекта."""
    table = _clean(raw.table) or ""
    schema = _clean(raw.schema)
    database = _clean(raw.database)

    if schema is None and "." in table and supports_schemas(dialect):
        schema, table = table.split(".", 1)
        schema = _clean(schema)
        table = _clean(table) or ""

    if dialect == "clickhouse" and database is None and schema is not None:
        database, schema = schema, None

    if database is None:
        database = _clean(connection.database)

    if supports_schemas(dialect):
        if schema is None:
            schema = _DEFAULT_SCHEMAS.get(dialect)
    else:
        schema = None

    return PhysicalLocator(
        dialect=dialect,
        host=connection.host.strip(),
        port=connection.port,
        database=database,
        schema=schema,
        table=table,
    )


def build_physical_key(locator: PhysicalLocator) -> str:
    port = "" if locator.port is None else str(locator.port)
    return (
        f"{locator.dialect}://{locator.host}:{port}"
        f"/{locator.database or ''}/{locator.schema or ''}/{locator.table}"
    ).lower()
