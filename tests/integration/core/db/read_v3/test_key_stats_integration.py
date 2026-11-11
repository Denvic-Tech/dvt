from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from core.db.read_v3.errors import ReadV3PlanningError
from core.db.read_v3.key_stats import KeyStatsSource, collect_key_statistics
from core.db.read_v3.models import PartitionStrategy
from core.db.read_v3.partition_advice import advise_partitioning
from core.db.read_v3.planner import query as query_planner, table as table_planner
from core.db.read_v3.resolver import resolve_planner

import config

pytestmark = pytest.mark.docker_required

STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}
TOTAL_ROWS = 300_000
# `heavy` holds 42 in the first HEAVY_ROWS rows and unique values after them;
# `good` repeats each of GOOD_DISTINCT values TOTAL_ROWS / GOOD_DISTINCT times.
HEAVY_ROWS = 150_000
GOOD_DISTINCT = 50_000
CEILING = 100_000


@pytest.fixture
def no_segment_queries(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("no segment query may run after a failed skew check")

    for module in (table_planner, query_planner):
        monkeypatch.setattr(module, "build_range_segments", fail)
        monkeypatch.setattr(module, "build_hash_segments", fail)


def _advice(stats, **kwargs):
    return advise_partitioning(stats, **STRICT_PARTITIONING_KWARGS, **kwargs)


@pytest.fixture
def clickhouse_table(clickhouse_http_test_engine: sa.Engine):
    engine = clickhouse_http_test_engine
    table_name = f"rv3_key_stats_{uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE {table_name} (
                    id UInt64, heavy Int64, good Int64, maybe Nullable(Int64), label String
                ) ENGINE = MergeTree ORDER BY id
                """
            )
        )
        conn.execute(
            text(
                f"""
                INSERT INTO {table_name}
                SELECT number, if(number < {HEAVY_ROWS}, 42, toInt64(number)),
                       toInt64(number % {GOOD_DISTINCT}),
                       if(number % 10 = 0, NULL, toInt64(number)),
                       concat('l', toString(number % 1000))
                FROM numbers({TOTAL_ROWS})
                """
            )
        )
    yield engine, table_name
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))


def test_clickhouse_exact_statistics(clickhouse_table):
    engine, table_name = clickhouse_table
    stats = collect_key_statistics(engine, table_name=table_name, sample_rows=1_000_000)

    assert stats.total_rows == TOTAL_ROWS
    assert stats.sort_key == "id"
    assert stats.sample_method is None
    by_name = {column.name: column for column in stats.columns}
    assert stats.columns[0].name == "id"
    assert by_name["id"].indexed is True
    heavy = by_name["heavy"]
    assert (heavy.source, heavy.estimated) == (KeyStatsSource.EXACT, False)
    assert (heavy.max_repeat, heavy.max_repeat_value) == (HEAVY_ROWS, 42)
    assert heavy.distinct_count == TOTAL_ROWS - HEAVY_ROWS + 1
    assert (heavy.min_value, heavy.max_value) == (42, TOTAL_ROWS - 1)
    good = by_name["good"]
    assert (good.distinct_count, good.max_repeat) == (GOOD_DISTINCT, TOTAL_ROWS // GOOD_DISTINCT)
    assert by_name["maybe"].null_count == TOTAL_ROWS // 10
    assert by_name["label"].distinct_count == 1000


def test_clickhouse_large_relation_statistics_are_estimates(clickhouse_table):
    engine, table_name = clickhouse_table
    stats = collect_key_statistics(
        engine, table_name=table_name, sample_rows=50_000, columns=["heavy", "maybe"]
    )

    assert stats.sample_method == "random_filter"
    heavy, maybe = stats.columns
    assert (heavy.source, heavy.estimated) == (KeyStatsSource.APPROXIMATE, True)
    assert heavy.max_repeat_value == 42
    assert heavy.max_repeat == pytest.approx(HEAVY_ROWS, rel=0.1)
    assert heavy.distinct_count == pytest.approx(TOTAL_ROWS - HEAVY_ROWS, rel=0.05)
    assert maybe.null_count == TOTAL_ROWS // 10


@pytest.mark.parametrize("mode", ["range", "hash"])
def test_clickhouse_planner_rejects_heavy_key_before_segments(
    clickhouse_table, no_segment_queries, mode
):
    engine, table_name = clickhouse_table
    with pytest.raises(ReadV3PlanningError) as raised:
        resolve_planner(mode="table").build_plan(
            engine=engine,
            table_name=table_name,
            columns=["id", "heavy"],
            partition_col="heavy",
            partition_grouping={"mode": mode},
            max_rows_per_partition=CEILING,
            **STRICT_PARTITIONING_KWARGS,
        )
    message = str(raised.value)
    assert f"value 42 occurs {HEAVY_ROWS} times" in message
    assert f"max_rows_per_partition={CEILING}" in message


def test_clickhouse_advice_recommends_the_even_key(clickhouse_table):
    engine, table_name = clickhouse_table
    stats = collect_key_statistics(
        engine, table_name=table_name, sample_rows=1_000_000, columns=["heavy", "good", "label"]
    )
    advice = _advice(stats, npartitions=10)

    assert advice.sizing.max_rows_per_partition == 120_000
    assert [item.name for item in advice.excluded] == ["heavy"]
    best = advice.recommendations[0]
    assert best.partition_col == "good"
    assert best.partition_grouping == {"mode": "hash", "buckets": 10}


def test_clickhouse_query_mode(clickhouse_table, no_segment_queries):
    engine, table_name = clickhouse_table
    query = f"SELECT id, heavy, good FROM {table_name} WHERE id >= 0"
    stats = collect_key_statistics(
        engine, query=query, sample_rows=1_000_000, columns=["heavy", "good"]
    )
    assert stats.total_rows == TOTAL_ROWS
    assert [column.max_repeat for column in stats.columns] == [HEAVY_ROWS, 6]

    with pytest.raises(ReadV3PlanningError, match=f"value 42 occurs {HEAVY_ROWS} times"):
        resolve_planner(mode="query").build_plan(
            engine=engine,
            query=query,
            partition_col="heavy",
            max_rows_per_partition=CEILING,
            **STRICT_PARTITIONING_KWARGS,
        )


@pytest.fixture
def postgres_table(postgres_test_engine: sa.Engine):
    engine = postgres_test_engine
    table_name = f"rv3_key_stats_{uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE {table_name} AS
                SELECT n AS id,
                       CASE WHEN n <= {HEAVY_ROWS} THEN 42 ELSE n END AS heavy,
                       n % {GOOD_DISTINCT} AS good,
                       CASE WHEN n % 10 = 0 THEN NULL ELSE n END AS maybe
                FROM generate_series(1, {TOTAL_ROWS}) AS n
                """
            )
        )
        conn.execute(text(f"ALTER TABLE {table_name} ADD PRIMARY KEY (id)"))
        conn.execute(text(f"ANALYZE {table_name}"))
    yield engine, table_name
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))


def test_postgres_exact_and_catalog_statistics(postgres_table):
    engine, table_name = postgres_table
    exact = collect_key_statistics(engine, table_name=table_name, sample_rows=1_000_000)
    assert (exact.total_rows, exact.total_rows_estimated) == (TOTAL_ROWS, False)
    assert exact.sort_key == "id"
    by_name = {column.name: column for column in exact.columns}
    assert (by_name["heavy"].max_repeat, by_name["heavy"].max_repeat_value) == (HEAVY_ROWS, 42)
    assert by_name["good"].distinct_count == GOOD_DISTINCT
    assert by_name["maybe"].null_count == TOTAL_ROWS // 10
    assert by_name["id"].indexed is True

    catalog = collect_key_statistics(
        engine, table_name=table_name, sample_rows=1_000, columns=["heavy", "maybe"]
    )
    assert catalog.sample_method == "pg_stats"
    heavy, maybe = catalog.columns
    assert (heavy.source, heavy.estimated) == (KeyStatsSource.CATALOG, True)
    assert heavy.max_repeat_value == 42
    assert heavy.max_repeat == pytest.approx(HEAVY_ROWS, rel=0.1)
    assert maybe.null_count == pytest.approx(TOTAL_ROWS // 10, rel=0.2)


@pytest.mark.parametrize("mode", ["range", "hash"])
def test_postgres_planner_rejects_heavy_key_from_catalog_estimate(
    postgres_table, no_segment_queries, mode
):
    engine, table_name = postgres_table
    with pytest.raises(
        ReadV3PlanningError, match=r"value '42' occurs \d+ times \(estimate from pg_stats\)"
    ):
        resolve_planner(mode="table").build_plan(
            engine=engine,
            table_name=table_name,
            schema="public",
            columns=["id", "heavy"],
            partition_col="heavy",
            partition_grouping={"mode": mode},
            max_rows_per_partition=CEILING,
            **STRICT_PARTITIONING_KWARGS,
        )


def test_postgres_advice_prefers_the_indexed_key_and_excludes_the_heavy_one(postgres_table):
    engine, table_name = postgres_table
    stats = collect_key_statistics(engine, table_name=table_name, sample_rows=1_000_000)
    advice = _advice(stats, npartitions=10)

    assert "heavy" in {item.name for item in advice.excluded}
    ranked = [item.partition_col for item in advice.recommendations]
    # The nullable key ranks after the non-null one of the same tier and skew.
    assert ranked[:3] == ["id", "good", "maybe"]
    assert advice.recommendations[0].strategy == PartitionStrategy.RANGE
