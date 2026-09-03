from __future__ import annotations

import json
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.errors import ReadV3PlanningError
from core.db.read_v3.resolver import resolve_executor, resolve_planner

import config

pytestmark = pytest.mark.docker_required


STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}


def _table_name(prefix: str) -> str:
    return f"rv3_{prefix}_{uuid4().hex[:8]}"


def _drop_table(engine: sa.Engine, table_name: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))


def _seed(engine: sa.Engine, table_name: str) -> None:
    rows = [
        {"id": 1, "payload": json.dumps({"alpha": 1}), "kind": "alpha"},
        {"id": 2, "payload": json.dumps(["beta", 2]), "kind": "beta"},
    ]
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE {table_name} (
                    id INTEGER PRIMARY KEY,
                    payload JSONB,
                    kind TEXT NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                INSERT INTO {table_name} (id, payload, kind)
                VALUES (:id, CAST(:payload AS JSONB), :kind)
                """
            ),
            rows,
        )


def test_read_v3_table_mode_supports_json_output_postgres(
    postgres_test_engine: sa.Engine,
) -> None:
    engine = postgres_test_engine
    table_name = _table_name("json_tbl")
    _drop_table(engine, table_name)

    try:
        _seed(engine, table_name)
        planner = resolve_planner(mode="table")
        plan = planner.build_plan(
            engine=engine,
            table_name=table_name,
            columns=["id", "payload"],
            partition_col="id",
            npartitions=2,
            **STRICT_PARTITIONING_KWARGS,
        )
        executor = resolve_executor(engine)
        result = (
            frame_from_executor(executor, plan)
            .compute()
            .reset_index(drop=True)
            .sort_values("id")
            .reset_index(drop=True)
        )

        assert result["payload"].dtype == object
        assert result["payload"].tolist() == [{"alpha": 1}, ["beta", 2]]
    finally:
        _drop_table(engine, table_name)


def test_read_v3_query_mode_supports_json_output_postgres(
    postgres_test_engine: sa.Engine,
) -> None:
    engine = postgres_test_engine
    table_name = _table_name("json_qry")
    _drop_table(engine, table_name)

    try:
        _seed(engine, table_name)
        planner = resolve_planner(mode="query")
        plan = planner.build_plan(
            engine=engine,
            query=f"SELECT id, payload FROM {table_name}",
            partition_col="id",
            npartitions=2,
            **STRICT_PARTITIONING_KWARGS,
        )
        executor = resolve_executor(engine)
        result = (
            frame_from_executor(executor, plan)
            .compute()
            .reset_index(drop=True)
            .sort_values("id")
            .reset_index(drop=True)
        )

        assert result["payload"].dtype == object
        assert result["payload"].tolist() == [{"alpha": 1}, ["beta", 2]]
    finally:
        _drop_table(engine, table_name)


def test_read_v3_table_mode_rejects_json_partition_key_postgres(
    postgres_test_engine: sa.Engine,
) -> None:
    engine = postgres_test_engine
    table_name = _table_name("json_key")
    _drop_table(engine, table_name)

    try:
        _seed(engine, table_name)
        planner = resolve_planner(mode="table")
        with pytest.raises(
            ReadV3PlanningError,
            match=r"does not support JSON partition keys in table mode.*column='payload'.*kind='json'.*type='JSONB'",
        ):
            planner.build_plan(
                engine=engine,
                table_name=table_name,
                columns=["id"],
                partition_col="payload",
                npartitions=2,
                **STRICT_PARTITIONING_KWARGS,
            )
    finally:
        _drop_table(engine, table_name)


def test_read_v3_query_mode_rejects_json_partition_key_postgres(
    postgres_test_engine: sa.Engine,
) -> None:
    engine = postgres_test_engine
    table_name = _table_name("json_qkey")
    _drop_table(engine, table_name)

    try:
        _seed(engine, table_name)
        planner = resolve_planner(mode="query")
        with pytest.raises(
            ReadV3PlanningError,
            match=r"does not support JSON partition keys in query mode.*column='payload'.*kind='json'.*type='jsonb'",
        ):
            planner.build_plan(
                engine=engine,
                query=f"SELECT id, payload FROM {table_name}",
                partition_col="payload",
                npartitions=2,
                **STRICT_PARTITIONING_KWARGS,
            )
    finally:
        _drop_table(engine, table_name)
