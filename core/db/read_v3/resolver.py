from typing import Literal, overload

from sqlalchemy.engine import Engine

from core.db.read_v3.dialects import resolve_dialect
from core.db.read_v3.errors import ReadV3ConfigError
from core.db.read_v3.executors.ch import ClickHouseReadExecutor
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


def resolve_executor(engine: Engine):
    dialect = resolve_dialect(engine)
    if dialect.name == "clickhouse":
        return ClickHouseReadExecutor(engine, dialect=dialect)
    return SQLReadExecutor(engine, dialect=dialect)
