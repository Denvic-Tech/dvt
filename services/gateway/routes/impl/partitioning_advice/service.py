"""Read partitioning advice for a saved SQL connection, shared by the Gateway route and MCP.

Statistics queries run under the ``query_database_readonly`` policy: user SQL must be one
read-only SELECT/WITH statement, and every data query runs in a read-only session with a
statement timeout (ClickHouse: ``readonly=1`` and ``max_execution_time``). The whole request is
bounded by ``READ_V3_KEY_STATS_TIMEOUT_SEC``.
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import asdict
from datetime import date, datetime, time as dt_time
from typing import Any

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from core.db.connect.clickhouse import build_clickhouse_client_kwargs, create_clickhouse_client
from core.db.connect.engine import build_engine_from_connection_string
from core.db.read_v3.errors import ReadV3ConfigError, ReadV3PlanningError
from core.db.read_v3.key_stats import RelationKeyStats, collect_key_statistics
from core.db.read_v3.partition_advice import PartitionAdvice, advise_partitioning
from core.db.read_v3.sql_runner import execute_literal_sql

from services.gateway.routes.internal.ai_mcp.data import (
    _configure_sync_readonly,
    _parse_readonly_sql,
)
from services.gateway.routes.internal.ai_mcp.errors import AIMCPHTTPError
from services.gateway.routes.internal.ai_mcp.redaction import redact_log_message

from src.exception_registry.utils import safe_exception_message

import config

from .schemas import PartitioningAdviceRequest, PartitioningAdviceResponse

# SQLAlchemy dialect name -> connection type of the read-only session policy.
_READONLY_CONNECTION_TYPES = {
    "postgresql": "postgres",
    "mysql": "mysql",
    "mariadb": "mysql",
    "oracle": "oracle",
    "clickhouse": "clickhouse",
}
_CONNECT_TIMEOUT_SEC = 25


class PartitioningAdviceError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _safe_message(exc: Exception) -> str:
    """Driver errors can echo connection URLs or credentials: redact before returning them."""
    return str(redact_log_message(safe_exception_message(exc, max_length=500)))


class _ReadOnlyQueryRunner:
    """``query_df`` for key statistics: every statement in a read-only session."""

    def __init__(self, engine: Engine, connection_type: str | None, timeout_sec: int) -> None:
        self._engine = engine
        self._connection_type = connection_type
        self._timeout_sec = timeout_sec
        self._clickhouse_client = None

    def __call__(self, sql: str) -> pd.DataFrame:
        if self._connection_type == "clickhouse":
            if self._clickhouse_client is None:
                self._clickhouse_client = create_clickhouse_client(
                    build_clickhouse_client_kwargs(self._engine)
                )
            return self._clickhouse_client.query_df(
                sql, settings={"readonly": 1, "max_execution_time": self._timeout_sec}
            )
        with self._engine.connect() as connection:
            transaction = connection.begin()
            try:
                if self._connection_type is not None:
                    _configure_sync_readonly(connection, self._connection_type, self._timeout_sec)
                result = execute_literal_sql(connection, sql)
                if not result.returns_rows:
                    return pd.DataFrame()
                return pd.DataFrame(result.fetchall(), columns=list(result.keys()))
            finally:
                transaction.rollback()

    def close(self) -> None:
        if self._clickhouse_client is not None:
            self._clickhouse_client.close()


def _install_readonly_session_defaults(
    engine: Engine, connection_type: str | None, timeout_sec: int
) -> None:
    """Make every new session read-only, covering metadata paths that bypass the runner."""
    if connection_type == "postgres":
        statements = (
            "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY",
            f"SET statement_timeout = {timeout_sec * 1000}",
        )
    elif connection_type == "mysql":
        statements = (
            "SET SESSION TRANSACTION READ ONLY",
            f"SET SESSION MAX_EXECUTION_TIME = {timeout_sec * 1000}",
        )
    else:
        return

    def _on_connect(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            for statement in statements:
                cursor.execute(statement)
        finally:
            cursor.close()
        dbapi_connection.commit()

    sa.event.listen(engine, "connect", _on_connect)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        result = value
    elif isinstance(value, float):
        result = None if math.isnan(value) or math.isinf(value) else value
    elif isinstance(value, datetime | date | dt_time):
        result = value.isoformat()
    elif isinstance(value, bytes):
        result = value.hex()
    else:
        result = str(value)
    return result


def _collect(
    engine: Engine,
    request: PartitioningAdviceRequest,
    query: str | None,
    connection_type: str | None,
    timeout_sec: int,
) -> RelationKeyStats:
    runner = _ReadOnlyQueryRunner(engine, connection_type, timeout_sec)
    try:
        return collect_key_statistics(
            engine,
            sample_rows=config.DASK_PARTITIONING.READ_V3_KEY_STATS_SAMPLE_ROWS,
            table_name=request.table_name,
            schema=request.schema_name,
            query=query,
            columns=request.columns,
            read_columns=request.read_columns,
            candidate_limit=request.candidate_limit,
            query_df=runner,
        )
    finally:
        runner.close()


def build_response(
    stats: RelationKeyStats, advice: PartitionAdvice, elapsed_ms: int
) -> PartitioningAdviceResponse:
    relation = asdict(stats)
    statistics = relation.pop("columns")
    for item in statistics:
        for key in ("max_repeat_value", "min_value", "max_value"):
            item[key] = _json_value(item[key])
    payload = asdict(advice)
    return PartitioningAdviceResponse.model_validate(
        {
            "relation": relation,
            "statistics": statistics,
            "sizing": payload["sizing"],
            "recommendations": payload["recommendations"],
            "excluded": payload["excluded"],
            "warnings": payload["warnings"],
            "elapsed_ms": elapsed_ms,
        }
    )


def _readonly_query(sql_code: str, connection_type: str | None) -> str:
    if connection_type is None:
        raise PartitioningAdviceError(
            422, "UNSAFE_SQL", "A safe read-only session is unavailable for this connector."
        )
    try:
        parsed_sql, is_explain = _parse_readonly_sql(sql_code, connection_type)
    except AIMCPHTTPError as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        raise PartitioningAdviceError(
            exc.status_code,
            str(detail.get("code", "UNSAFE_SQL")),
            str(detail.get("message", "SQL query is not allowed.")),
        ) from exc
    if is_explain:
        raise PartitioningAdviceError(422, "UNSAFE_SQL", "EXPLAIN cannot be profiled.")
    return parsed_sql


def _build_engine(connection_string: str, database_name: str | None) -> Engine:
    try:
        return build_engine_from_connection_string(
            connection_string=connection_string,
            database_name=database_name,
            connect_timeout_sec=_CONNECT_TIMEOUT_SEC,
        )
    except Exception as exc:
        raise PartitioningAdviceError(
            422, "CONNECTION_FAILED", "The saved connection could not be opened."
        ) from exc


async def suggest_read_partitioning(
    connection_string: str, request: PartitioningAdviceRequest
) -> PartitioningAdviceResponse:
    """Profile candidate keys of a table or query and rank them for read_v3 readers."""
    settings = config.DASK_PARTITIONING
    timeout_sec = settings.READ_V3_KEY_STATS_TIMEOUT_SEC
    engine = _build_engine(connection_string, request.database_name)
    started = time.perf_counter()
    try:
        connection_type = _READONLY_CONNECTION_TYPES.get(engine.dialect.name.lower())
        query = None
        if request.sql_code is not None:
            query = _readonly_query(request.sql_code, connection_type)
        _install_readonly_session_defaults(engine, connection_type, timeout_sec)
        try:
            stats = await asyncio.wait_for(
                asyncio.to_thread(_collect, engine, request, query, connection_type, timeout_sec),
                timeout=timeout_sec,
            )
        except TimeoutError as exc:
            raise PartitioningAdviceError(
                504,
                "ADVICE_TIMEOUT",
                f"Key statistics did not finish within {timeout_sec} s; profile fewer columns.",
            ) from exc
        except (ReadV3ConfigError, ReadV3PlanningError) as exc:
            raise PartitioningAdviceError(422, "INVALID_RELATION", _safe_message(exc)) from exc
        except Exception as exc:
            raise PartitioningAdviceError(
                422,
                "STATISTICS_FAILED",
                f"Key statistics failed ({type(exc).__name__}): {_safe_message(exc)}",
            ) from exc
    finally:
        engine.dispose()
    try:
        advice = advise_partitioning(
            stats,
            min_rows_per_partition=settings.MIN_ROWS_PER_PART,
            target_partition_mem_mb=settings.TARGET_PARTITION_MEM_MB,
            partitioning_overhead_coef=settings.OVERHEAD_COEF,
            max_partitions=settings.MAX_PARTITIONS,
            npartitions=request.npartitions,
            max_rows_per_partition=request.max_rows_per_partition,
        )
    except ReadV3PlanningError as exc:
        raise PartitioningAdviceError(422, "INVALID_ARGUMENTS", _safe_message(exc)) from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    return build_response(stats, advice, elapsed_ms)
