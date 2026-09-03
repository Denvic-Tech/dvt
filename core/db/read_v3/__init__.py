"""Strict read_v3 package for partitioned database reads with known Dask divisions."""

from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.datetime_precision import (
    ReadV3DateTimePrecision,
    normalize_datetime_precision,
    pandas_datetime_dtype,
)
from core.db.read_v3.errors import (
    ReadV3ConfigError,
    ReadV3DialectError,
    ReadV3Error,
    ReadV3ExecutionError,
    ReadV3PlanningError,
)
from core.db.read_v3.resolver import resolve_executor, resolve_planner

__all__ = [
    "ReadV3ConfigError",
    "ReadV3DateTimePrecision",
    "ReadV3DialectError",
    "ReadV3Error",
    "ReadV3ExecutionError",
    "ReadV3PlanningError",
    "frame_from_executor",
    "normalize_datetime_precision",
    "pandas_datetime_dtype",
    "resolve_executor",
    "resolve_planner",
]
