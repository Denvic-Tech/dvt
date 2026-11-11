from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa

from core.db.read_v3.dialects.clickhouse import ClickHouseDialect
from core.db.read_v3.dialects.mssql import MssqlDialect
from core.db.read_v3.dialects.oracle import OracleDialect
from core.db.read_v3.dialects.postgres import PostgresDialect
from core.db.read_v3.dialects.sqlite import SqliteDialect
from core.db.read_v3.errors import ReadV3ConfigError, ReadV3PlanningError
from core.db.read_v3.key_stats import KeyStatsSource, collect_key_statistics
from core.db.read_v3.models import ReadMode, ValueKind

ROWS = 2_000
SKEWED_ROWS = 300


@pytest.fixture
def engine(tmp_path) -> sa.Engine:
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'stats.db').as_posix()}")
    rows = [
        {
            "id": idx,
            "skewed": 7 if idx <= SKEWED_ROWS else idx,
            "category": f"c{idx % 40}",
            "sale_date": date(2025, 1 + idx % 12, 1 + idx % 28).isoformat(),
            "maybe": None if idx % 10 == 0 else idx,
            "flag": idx % 2 == 0,
        }
        for idx in range(1, ROWS + 1)
    ]
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE sales (id INTEGER PRIMARY KEY, skewed INTEGER, category TEXT, "
            "sale_date DATE, maybe INTEGER, flag BOOLEAN)"
        )
        conn.execute(
            sa.text(
                "INSERT INTO sales VALUES (:id, :skewed, :category, :sale_date, :maybe, :flag)"
            ),
            rows,
        )
    yield engine
    engine.dispose()


def test_small_table_is_profiled_exactly(engine):
    stats = collect_key_statistics(engine, table_name="sales", sample_rows=1_000_000)

    assert stats.mode == ReadMode.TABLE
    assert stats.total_rows == ROWS
    assert stats.sample_method is None
    assert stats.sort_key == "id"
    by_name = {column.name: column for column in stats.columns}
    # Index-leading columns are profiled first; BOOLEAN is not a key candidate by default.
    assert stats.columns[0].name == "id"
    assert "flag" not in by_name
    skewed = by_name["skewed"]
    assert (skewed.source, skewed.estimated) == (KeyStatsSource.EXACT, False)
    assert skewed.distinct_count == ROWS - SKEWED_ROWS + 1
    assert (skewed.max_repeat, skewed.max_repeat_value) == (SKEWED_ROWS, 7)
    assert (skewed.min_value, skewed.max_value) == (7, ROWS)
    assert by_name["id"].indexed is True
    assert by_name["maybe"].null_count == ROWS // 10
    assert by_name["sale_date"].value_kind == ValueKind.DATE
    assert by_name["sale_date"].min_value == date(2025, 1, 1)
    assert by_name["category"].distinct_count == 40


def test_large_relation_is_sampled_and_marked_as_estimate(engine):
    stats = collect_key_statistics(
        engine, table_name="sales", sample_rows=500, columns=["skewed", "maybe"]
    )

    assert stats.sample_method == "first_rows"
    assert stats.sample_rows == 500
    skewed, maybe = stats.columns
    assert (skewed.source, skewed.estimated) == (KeyStatsSource.SAMPLE, True)
    # 300 of the first 500 rows, scaled to 2 000 rows.
    assert skewed.max_repeat == SKEWED_ROWS * ROWS // 500
    assert maybe.null_count == ROWS // 10
    assert "first_rows sample of 500 rows" in skewed.note


def test_query_mode_profiles_the_embedded_result(engine):
    stats = collect_key_statistics(
        engine,
        query="SELECT id, skewed AS key_col FROM sales WHERE id > 100",
        sample_rows=1_000_000,
        columns=["KEY_COL"],
    )

    assert stats.mode == ReadMode.QUERY
    assert stats.total_rows == ROWS - 100
    (column,) = stats.columns
    assert column.name == "key_col"
    assert column.max_repeat == SKEWED_ROWS - 100


def test_explicit_unsupported_and_unknown_columns(engine):
    stats = collect_key_statistics(
        engine, table_name="sales", sample_rows=1_000_000, columns=["flag", "id"]
    )
    flag = next(column for column in stats.columns if column.name == "flag")
    assert flag.available is False
    assert "not usable as a partition key" in flag.note

    with pytest.raises(ReadV3PlanningError, match="'missing' was not found"):
        collect_key_statistics(
            engine, table_name="sales", sample_rows=1_000_000, columns=["missing"]
        )
    with pytest.raises(ReadV3ConfigError, match="exactly one"):
        collect_key_statistics(engine, sample_rows=10)


def test_clickhouse_statistics_sql():
    dialect = ClickHouseDialect()
    columns = [("a", "`a`"), ("b c", "`b c`")]

    stats_sql = dialect.key_stats_query("FROM `db`.`t`", columns)
    assert stats_sql.count(" UNION ALL ") == 1
    assert "SELECT 'b c' AS column_name" in stats_sql
    assert (
        "FROM (SELECT `a` AS dvt_kv, count() AS dvt_kc FROM `db`.`t` GROUP BY dvt_kv)" in stats_sql
    )
    assert "argMaxIf(dvt_kv, dvt_kc, isNotNull(dvt_kv))" in stats_sql

    aggregates_sql = dialect.key_aggregates_query("FROM t", columns)
    assert aggregates_sql.startswith("SELECT count() AS total_rows, uniq(`a`) AS distinct_0")
    assert "countIf(isNull(`b c`)) AS nulls_1" in aggregates_sql

    assert dialect.heaviest_value_query("FROM t", "`a`") == (
        "SELECT `a` AS dvt_heavy_value, count() AS dvt_heavy_count FROM t "
        "GROUP BY `a` ORDER BY dvt_heavy_count DESC LIMIT 1"
    )
    assert "database = currentDatabase() AND name = 't'" in dialect.table_sort_key_query(
        table_name="t", database=None
    )


@pytest.mark.parametrize(
    ("native_sampling", "expected_sql", "method"),
    [
        (True, "FROM (SELECT `a` FROM `t` SAMPLE 1000) dvt_key_sample", "clickhouse_sample"),
        (
            False,
            "FROM (SELECT `a` FROM `t` WHERE rand() < 42949672) dvt_key_sample",
            "random_filter",
        ),
    ],
)
def test_clickhouse_sample_relation(native_sampling, expected_sql, method):
    relation = ClickHouseDialect().key_sample_relation(
        table_sql="`t`",
        select_list_sql="`a`",
        relation_sql="FROM `t`",
        sample_rows=1_000,
        total_rows=100_000,
        native_sampling=native_sampling,
    )
    assert relation == (expected_sql, method)


def test_table_sample_clauses_and_query_mode_fallback():
    common = {"select_list_sql": "a", "sample_rows": 1_000, "total_rows": 100_000}
    postgres = PostgresDialect().key_sample_relation(
        table_sql='"t"', relation_sql='FROM "t"', **common
    )
    assert postgres == (
        'FROM (SELECT a FROM "t" TABLESAMPLE SYSTEM (1.000000) REPEATABLE (17)) dvt_key_sample',
        "tablesample_system",
    )
    mssql = MssqlDialect().key_sample_relation(table_sql="[t]", relation_sql="FROM [t]", **common)
    assert "TABLESAMPLE (1.000000 PERCENT) REPEATABLE (17)" in mssql[0]
    oracle = OracleDialect().key_sample_relation(
        table_sql="t", relation_sql="FROM t", select_list_sql="a", sample_rows=10, total_rows=10
    )
    assert "SAMPLE (99.999999) SEED (17)" in oracle[0]
    query = PostgresDialect().key_sample_relation(
        table_sql=None, relation_sql="FROM user_query", **common
    )
    assert query == (
        "FROM (SELECT * FROM (SELECT a FROM user_query) __dvt_cap LIMIT 1000 OFFSET 0) "
        "dvt_key_sample",
        "first_rows",
    )


def test_postgres_catalog_statistics_sql_and_generic_defaults():
    sql = PostgresDialect().column_statistics_query(
        table_name="sales", schema="public", column_names=["id", "it's"]
    )
    assert "FROM pg_catalog.pg_stats s" in sql
    assert "s.schemaname = 'public' AND s.tablename = 'sales'" in sql
    assert "s.attname IN ('id', 'it''s')" in sql

    base = SqliteDialect()
    with pytest.raises(NotImplementedError):
        base.heaviest_value_query("FROM t", "a")
    with pytest.raises(NotImplementedError):
        base.key_stats_query("FROM t", [])
    assert "GROUP BY a) dvt_key_groups" in base.key_profile_query("FROM t", "a")
