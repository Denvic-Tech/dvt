from typing import Literal, overload

from sqlalchemy.engine import Engine

from core.db.read_v3.dialects import resolve_dialect
from core.db.read_v3.errors import ReadV3ConfigError
from core.db.read_v3.executors.ch import ClickHouseReadExecutor
from core.db.read_v3.executors.pg import PostgresReadExecutor, adbc_available
from core.db.read_v3.executors.sql import SQLReadExecutor
from core.db.read_v3.planner.query import QueryReadPlanner
from core.db.read_v3.planner.table import TableReadPlanner


@overload
def resolve_planner(mode: Literal["table"] = "table") -> TableReadPlanner: ...

@overload
def resolve_planner(mode: Literal["query"] = "query") -> QueryReadPlanner: ...

def resolve_planner(mode: Literal["table", "query"] = "table") -> TableReadPlanner | QueryReadPlanner:
    if mode == "table":
        return TableReadPlanner()
    if mode == "query":
        return QueryReadPlanner()
    raise ReadV3ConfigError(f"Unsupported read_v3 mode={mode!r}; expected 'table' or 'query'")


def resolve_executor(
    engine: Engine,
    *,
    max_concurrent_queries: int | None = None,
    pg_arrow_read: bool = True,
):
    """Executor for the engine's dialect.

    ``pg_arrow_read`` enables the ADBC Arrow segment fetch for PostgreSQL when
    ``adbc_driver_postgresql`` is installed; otherwise PostgreSQL uses ``SQLReadExecutor``.
    """
    dialect = resolve_dialect(engine)
    if dialect.name == "clickhouse":
        return ClickHouseReadExecutor(
            engine, dialect=dialect, max_concurrent_queries=max_concurrent_queries
        )
    if dialect.name == "postgresql" and pg_arrow_read and adbc_available():
        return PostgresReadExecutor(
            engine, dialect=dialect, max_concurrent_queries=max_concurrent_queries
        )
    return SQLReadExecutor(engine, dialect=dialect, max_concurrent_queries=max_concurrent_queries)
