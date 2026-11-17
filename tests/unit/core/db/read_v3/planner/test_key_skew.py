from __future__ import annotations

import pandas as pd
import pytest
import sqlalchemy as sa

from core.db.read_v3.dialects.clickhouse import ClickHouseDialect
from core.db.read_v3.dialects.postgres import PostgresDialect
from core.db.read_v3.dialects.sqlite import SqliteDialect
from core.db.read_v3.errors import ReadV3PlanningError
from core.db.read_v3.planner import TableReadPlanner, key_skew, table as table_planner

import config

STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}


@pytest.fixture
def queries(monkeypatch):
    """Answer lookup SQL by its first matching fragment; record every statement."""
    executed: list[str] = []
    answers: dict[str, pd.DataFrame | Exception] = {}

    def run(_engine, sql: str) -> pd.DataFrame:
        executed.append(sql)
        for fragment, answer in answers.items():
            if fragment in sql:
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise AssertionError(f"unexpected SQL: {sql}")

    monkeypatch.setattr(key_skew, "read_sql_df", run)
    return executed, answers


def _check(dialect, **overrides) -> str:
    kwargs = {
        "engine": object(),
        "dialect": dialect,
        "cte_prefix_sql": None,
        "relation_sql": "FROM sales",
        "key_sql": "code",
        "key_name": "code",
        "total_rows": 1_000_000,
        "max_rows_per_partition": 100_000,
        **overrides,
    }
    return key_skew.check_partition_key_skew(**kwargs)


def test_relation_within_the_ceiling_needs_no_lookup(queries):
    executed, _ = queries
    assert _check(ClickHouseDialect(), total_rows=100_000) == "skipped(relation fits one segment)"
    assert executed == []


def test_clickhouse_exact_heavy_value_fails_planning(queries):
    _, answers = queries
    answers["dvt_heavy_count"] = pd.DataFrame(
        {"dvt_heavy_value": [75588], "dvt_heavy_count": [404_499]}
    )
    with pytest.raises(ReadV3PlanningError) as raised:
        _check(ClickHouseDialect())
    message = str(raised.value)
    assert "Partition key 'code'" in message
    assert "max_rows_per_partition=100000" in message
    assert "value 75588 occurs 404499 times" in message
    assert "suggest_read_partitioning" in message
    assert "estimate" not in message


def test_clickhouse_key_within_the_ceiling_passes(queries):
    _, answers = queries
    answers["dvt_heavy_count"] = pd.DataFrame(
        {"dvt_heavy_value": ["a"], "dvt_heavy_count": [100_000]}
    )
    assert _check(ClickHouseDialect()) == "ok(max_repeat=100000, source=exact)"


@pytest.mark.parametrize(
    ("top_freq", "null_frac", "expected"),
    [
        # 120 000 rows: above the ceiling but inside the 25% margin of an estimate.
        (0.12, 0.0, "ok(max_repeat=120000, source=pg_stats)"),
        (0.2, 0.0, "value 'hot' occurs 200000 times (estimate from pg_stats)"),
        (0.01, 0.3, "NULL keys occur 300000 times (estimate from pg_stats)"),
    ],
)
def test_postgres_table_uses_catalog_estimates(queries, top_freq, null_frac, expected):
    _, answers = queries
    answers["pg_stats"] = pd.DataFrame(
        {
            "column_name": ["code"],
            "inherited": [False],
            "null_frac": [null_frac],
            "n_distinct": [-0.5],
            "top_value": ["hot"],
            "top_freq": [top_freq],
            "hist_min": ["a"],
            "hist_max": ["z"],
        }
    )
    if expected.startswith("ok("):
        assert _check(PostgresDialect(), table_name="sales") == expected
        return
    with pytest.raises(ReadV3PlanningError, match=expected.replace("(", r"\(").replace(")", r"\)")):
        _check(PostgresDialect(), table_name="sales")


def test_dialects_without_a_cheap_lookup_and_lookup_failures_skip_the_check(queries):
    executed, answers = queries
    # PostgreSQL query mode: catalog statistics do not describe a query result.
    assert _check(PostgresDialect()) == "skipped(no cheap lookup for dialect postgresql)"
    assert _check(SqliteDialect(), table_name="sales") == (
        "skipped(no cheap lookup for dialect sqlite)"
    )
    assert executed == []
    answers["dvt_heavy_count"] = RuntimeError("timeout")
    assert _check(ClickHouseDialect()) == "skipped(RuntimeError)"


@pytest.fixture
def engine(tmp_path) -> sa.Engine:
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'skew.db').as_posix()}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE sales (id INTEGER PRIMARY KEY, code INTEGER)")
        conn.execute(
            sa.text("INSERT INTO sales VALUES (:id, :code)"),
            [{"id": idx, "code": idx % 3} for idx in range(1, 101)],
        )
    yield engine
    engine.dispose()


@pytest.mark.parametrize("mode", ["range", "hash"])
def test_planner_runs_the_check_before_any_segment_query(engine, monkeypatch, mode):
    calls: list[dict] = []

    def failing_check(**kwargs):
        calls.append(kwargs)
        raise ReadV3PlanningError("heavy key")

    def no_segments(*_args, **_kwargs):
        raise AssertionError("segments must not be built after a failed skew check")

    monkeypatch.setattr(table_planner, "check_partition_key_skew", failing_check)
    monkeypatch.setattr(table_planner, "build_range_segments", no_segments)
    monkeypatch.setattr(table_planner, "build_hash_segments", no_segments)
    with pytest.raises(ReadV3PlanningError, match="heavy key"):
        TableReadPlanner().build_plan(
            engine,
            "sales",
            partition_col="code",
            partition_grouping={"mode": mode},
            max_rows_per_partition=10,
            **STRICT_PARTITIONING_KWARGS,
        )
    assert calls[0]["key_name"] == "code"
    assert calls[0]["max_rows_per_partition"] == 10
    assert calls[0]["table_name"] == "sales"


def test_planner_check_can_be_disabled(engine, monkeypatch):
    def unexpected(**_kwargs):
        raise AssertionError("the check is disabled")

    monkeypatch.setattr(table_planner, "check_partition_key_skew", unexpected)
    plan = TableReadPlanner().build_plan(
        engine,
        "sales",
        partition_col="id",
        key_skew_check=False,
        **STRICT_PARTITIONING_KWARGS,
    )
    assert "key_skew_check=disabled" in plan.extra_warnings
