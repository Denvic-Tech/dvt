"""Strict write_v3 package for typed append/truncate/upsert database writes."""

import dask.dataframe as dd
import sqlalchemy as sa

from core.db.write_v3.errors import (
    WriteV3ConfigError,
    WriteV3DialectError,
    WriteV3Error,
    WriteV3ExecutionError,
    WriteV3PlanningError,
)
from core.db.write_v3.models import (
    ExtraColumnsMode,
    MissingColumnsMode,
    UpsertConfig,
    WriteDiagnostic,
    WriteMode,
    WritePlan,
    WriteRequest,
    WriteResult,
    WriteTarget,
)
from core.db.write_v3.planner import plan_write
from core.db.write_v3.resolver import resolve_executor


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
    "WriteRequest",
    "WritePlan",
    "WriteResult",
    "WriteDiagnostic",
    "UpsertConfig",
    "WriteV3Error",
    "WriteV3ConfigError",
    "WriteV3PlanningError",
    "WriteV3ExecutionError",
    "WriteV3DialectError",
]
