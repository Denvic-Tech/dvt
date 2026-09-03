from __future__ import annotations

import sqlalchemy as sa


UNSUPPORTED_DATABASE_DIALECTS = {"sqlite", "oracle"}
AUTOCOMMIT_DATABASE_DIALECTS = {"postgresql", "mssql"}


def quote_database_name(engine: sa.Engine, database_name: str) -> str:
    return engine.dialect.identifier_preparer.quote(database_name)


def database_exists(engine: sa.Engine, database_name: str) -> bool:
    dialect_name = engine.dialect.name.lower()
    existence_queries = {
        "postgresql": "SELECT 1 FROM pg_database WHERE datname = :database_name",
        "mssql": "SELECT 1 FROM sys.databases WHERE name = :database_name",
        "mysql": "SELECT 1 FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = :database_name",
        "mariadb": "SELECT 1 FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = :database_name",
        "clickhouse": "SELECT 1 FROM system.databases WHERE name = :database_name",
    }

    if dialect_name in UNSUPPORTED_DATABASE_DIALECTS:
        raise ValueError(f'Dialect "{dialect_name}" does not support CREATE DATABASE via this endpoint.')

    query = existence_queries.get(dialect_name)
    if query is None:
        raise ValueError(f'Dialect "{dialect_name}" is not supported by /ddl/create-database.')

    with engine.connect() as conn:
        result = conn.execute(sa.text(query), {"database_name": database_name})
        return result.scalar() is not None


def build_create_database_sql(engine: sa.Engine, database_name: str) -> str:
    dialect_name = engine.dialect.name.lower()
    if dialect_name in UNSUPPORTED_DATABASE_DIALECTS:
        raise ValueError(f'Dialect "{dialect_name}" does not support CREATE DATABASE via this endpoint.')

    if dialect_name not in {"postgresql", "mssql", "mysql", "mariadb", "clickhouse"}:
        raise ValueError(f'Dialect "{dialect_name}" is not supported by /ddl/create-database.')

    quoted_database_name = quote_database_name(engine, database_name)
    return f"CREATE DATABASE {quoted_database_name}"


def execute_create_database(engine: sa.Engine, sql: str) -> None:
    dialect_name = engine.dialect.name.lower()

    if dialect_name in AUTOCOMMIT_DATABASE_DIALECTS:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(sa.text(sql))
    else:
        with engine.begin() as conn:
            conn.execute(sa.text(sql))
