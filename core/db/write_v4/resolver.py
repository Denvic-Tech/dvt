from sqlalchemy.engine import Engine

from core.db.write_v4.dialects import resolve_dialect
from core.db.write_v4.executors.ch import ClickHouseWriteExecutor
from core.db.write_v4.executors.pg import PostgresWriteExecutor
from core.db.write_v4.executors.sql import SQLWriteExecutor


def resolve_executor(engine: Engine, *, pg_copy: bool = True):
    dialect = resolve_dialect(engine)
    if dialect.name == "clickhouse":
        return ClickHouseWriteExecutor(engine, dialect=dialect)
    # COPY needs psycopg 3 (``cursor.copy``); psycopg2 and other drivers keep executemany.
    if dialect.name == "postgresql" and pg_copy and engine.dialect.driver == "psycopg":
        return PostgresWriteExecutor(engine, dialect=dialect)
    return SQLWriteExecutor(engine, dialect=dialect)
