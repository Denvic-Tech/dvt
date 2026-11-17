from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.resolver import resolve_executor, resolve_planner

import config

pytestmark = pytest.mark.docker_required

STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}

NAME_COLUMN = "Наименование товара"
TOTAL_ROWS = 30_000
# Rows 0..19_999 share the 2-character prefix "Мо" but have distinct names.
LARGE_GROUP_ROWS = 20_000


def _seed_products(engine: sa.Engine, table_name: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE {table_name} (
                    id UInt64,
                    `{NAME_COLUMN}` String,
                    amount Int64
                ) ENGINE = MergeTree
                ORDER BY id
                """
            )
        )
        conn.execute(
            text(
                f"""
                INSERT INTO {table_name}
                SELECT
                    number + 1,
                    if(
                        number < {LARGE_GROUP_ROWS},
                        concat('Молоко ', toString(number)),
                        concat(
                            arrayElement(['Хлеб', 'Сыр', 'Чай', 'Кофе', 'Рис'], number % 5 + 1),
                            ' ',
                            toString(number)
                        )
                    ),
                    toInt64(number % 997) - 300
                FROM numbers({TOTAL_ROWS})
                """
            )
        )


def test_clickhouse_prefix_grouping_splits_oversized_group_by_key_hash(
    clickhouse_http_test_engine: sa.Engine,
) -> None:
    engine = clickhouse_http_test_engine
    table_name = f"rv3_grouping_split_{uuid4().hex[:8]}"
    _seed_products(engine, table_name)
    try:
        with engine.connect() as conn:
            expected_amount = int(conn.execute(text(f"SELECT sum(amount) FROM {table_name}")).scalar())

        plan = resolve_planner(mode="table").build_plan(
            engine=engine,
            table_name=table_name,
            columns=["id", NAME_COLUMN, "amount"],
            partition_col=NAME_COLUMN,
            partition_grouping={"mode": "prefix", "length": 2},
            npartitions=8,
            max_rows_per_partition=5_000,
            **STRICT_PARTITIONING_KWARGS,
        )

        # floor(0.8 * 5_000) = 4_000 rows per sub-segment -> ceil(20_000 / 4_000) = 5 buckets.
        sub_segments = [segment for segment in plan.segments if segment.label.startswith("Мо#")]
        assert [segment.label for segment in sub_segments] == [f"Мо#{bucket}/5" for bucket in range(5)]
        assert all(segment.expected_rows == 4_000 for segment in sub_segments)
        assert all("cityHash64" in segment.predicate_sql for segment in sub_segments)
        assert {segment.label for segment in plan.segments} - {
            segment.label for segment in sub_segments
        } == {"Хл", "Сы", "Ча", "Ко", "Ри"}
        assert plan.divisions == tuple(range(len(plan.segments) + 1))

        ddf = frame_from_executor(resolve_executor(engine), plan)
        result = ddf.compute()

        assert len(result) == TOTAL_ROWS
        assert not result["id"].duplicated().any()
        assert int(result["id"].sum()) == TOTAL_ROWS * (TOTAL_ROWS + 1) // 2
        assert int(result["amount"].sum()) == expected_amount
        assert int(result[NAME_COLUMN].str.startswith("Мо").sum()) == LARGE_GROUP_ROWS
    finally:
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
