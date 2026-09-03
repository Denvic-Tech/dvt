from __future__ import annotations

import logging

import sqlalchemy as sa


DIALECTS_WITHOUT_SCHEMA_SUPPORT = {"sqlite", "mysql", "mariadb", "clickhouse"}


def build_create_schema_sql(engine: sa.Engine, schema_name: str) -> str:
    dialect_name = engine.dialect.name.lower()

    if dialect_name in DIALECTS_WITHOUT_SCHEMA_SUPPORT:
        raise ValueError(f'Dialect "{dialect_name}" does not support CREATE SCHEMA.')

    if dialect_name == "oracle":
        quoted_schema_name = engine.dialect.identifier_preparer.quote_schema(schema_name)
        return f"CREATE SCHEMA AUTHORIZATION {quoted_schema_name}"

    return str(sa.schema.CreateSchema(schema_name).compile(dialect=engine.dialect)).strip()


def execute_create_schema(engine: sa.Engine, schema_name: str) -> None:
    sql = build_create_schema_sql(engine, schema_name)
    with engine.begin() as conn:
        conn.execute(sa.text(sql))


def ensure_schema_exists(
    *,
    engine: sa.Engine,
    schema_name: str | None,
    logger: logging.Logger | None = None,
) -> None:
    if not schema_name:
        return

    app_logger = logger or logging.getLogger(__name__)
    dialect_name = engine.dialect.name.lower()
    if dialect_name in DIALECTS_WITHOUT_SCHEMA_SUPPORT:
        app_logger.info(
            "Dialect Name=%s does not support schemas; skipping schema creation.",
            dialect_name,
        )
        return

    inspector = sa.inspect(engine)
    try:
        schema_exists = inspector.has_schema(schema_name)
    except NotImplementedError:
        return

    if schema_exists:
        return

    execute_create_schema(engine, schema_name)
