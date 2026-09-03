"""Strict write_v4 package for typed append/truncate/upsert database writes."""

import dask.dataframe as dd
import sqlalchemy as sa

from core.db.write_v4.errors import (
    WriteV4ConfigError,
    WriteV4DialectError,
    WriteV4Error,
    WriteV4ExecutionError,
    WriteV4PlanningError,
)
from core.db.write_v4.models import (
    ExtraColumnsMode,
    MissingColumnsMode,
    UpsertConfig,
    WriteColumnMapping,
    WriteDiagnostic,
    WriteMode,
    WritePlan,
    WriteRequest,
    WriteResult,
    WriteTarget,
)
from core.db.write_v4.column_resolution import (
    WriteColumnResolutionResult,
    WriteColumnResolutionRow,
    resolve_existing_table_write_columns,
    resolve_typed_create_write_columns,
)
from core.db.write_v4.planner import plan_write
from core.db.write_v4.resolver import resolve_executor


def write_dataframe(ddf: dd.DataFrame, engine: sa.Engine, request: WriteRequest) -> WriteResult:
    plan = plan_write(engine, request)
    executor = resolve_executor(engine)
    return executor.execute(ddf, request, plan)


__all__ = [
    "write_dataframe",
    "plan_write",
    "resolve_executor",
    "ExtraColumnsMode",
    "MissingColumnsMode",
    "WriteMode",
    "WriteTarget",
    "WriteColumnMapping",
    "WriteRequest",
    "WritePlan",
    "WriteResult",
    "WriteDiagnostic",
    "WriteColumnResolutionResult",
    "WriteColumnResolutionRow",
    "resolve_existing_table_write_columns",
    "resolve_typed_create_write_columns",
    "UpsertConfig",
    "WriteV4Error",
    "WriteV4ConfigError",
    "WriteV4PlanningError",
    "WriteV4ExecutionError",
    "WriteV4DialectError",
]
