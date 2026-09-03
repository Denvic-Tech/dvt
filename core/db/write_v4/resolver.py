from sqlalchemy.engine import Engine

from core.db.write_v4.dialects import resolve_dialect
from core.db.write_v4.executors.ch import ClickHouseWriteExecutor
from core.db.write_v4.executors.sql import SQLWriteExecutor


def resolve_executor(engine: Engine):
    dialect = resolve_dialect(engine)
    if dialect.name == "clickhouse":
        return ClickHouseWriteExecutor(engine, dialect=dialect)
    return SQLWriteExecutor(engine, dialect=dialect)
