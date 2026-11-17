from __future__ import annotations

import math
import random
import re
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
import sqlalchemy as sa

from core.db.read_v3.dialects.base import SQLDialect
from core.db.read_v3.dialects.clickhouse import ClickHouseDialect
from core.db.read_v3.dialects.mssql import MssqlDialect
from core.db.read_v3.dialects.mysql import MySQLDialect
from core.db.read_v3.dialects.oracle import OracleDialect
from core.db.read_v3.dialects.postgres import PostgresDialect
from core.db.read_v3.dialects.sqlite import SqliteDialect
from core.db.read_v3.planner import boundaries as boundaries_module
from core.db.read_v3.planner.boundaries import build_range_segments
from core.db.read_v3.resolver import resolve_planner

import config

STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}
RELATION = "FROM src"
ROWS = 997


class _SingleQuerySqlite(SqliteDialect):
    """SQLite dialect that runs another dialect's single-statement boundaries SQL.

    The window statements only interpolate ``relation_sql`` and ``key_sql``, so SQLite (window
    functions, ``%`` and a registered ``MOD``) runs them as the target database would.
    """

    def __init__(self, source: SQLDialect) -> None:
        self._source = source

    def range_boundaries_query(self, relation_sql, key_sql, *, page_size, non_null_rows):
        return self._source.range_boundaries_query(
            relation_sql,
            key_sql,
            page_size=page_size,
            non_null_rows=non_null_rows,
        )


class _BrokenSingleQuerySqlite(SqliteDialect):
    def range_boundaries_query(self, relation_sql, key_sql, *, page_size, non_null_rows):
        return "SELECT boundary_value FROM missing_table"


@pytest.fixture
def engine(tmp_path):
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'boundaries.db').as_posix()}")

    @sa.event.listens_for(engine, "connect")
    def _register_mod(dbapi_connection, _record):
        dbapi_connection.create_function("MOD", 2, lambda left, right: left % right)

    rng = random.Random(7)
    rows = []
    for idx in range(ROWS):
        # Duplicates, NULLs and an unsorted physical order in every key column.
        num = None if idx % 11 == 0 else rng.randint(-40, 160)
        rows.append(
            {
                "id": idx,
                "num": num,
                "txt": None if idx % 13 == 0 else f"k{rng.randint(0, 90):03d}",
                "real_v": None if idx % 17 == 0 else rng.randint(0, 50) / 4,
            }
        )
    rng.shuffle(rows)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE src (id INTEGER PRIMARY KEY, num INTEGER, txt TEXT, real_v REAL)"
        )
        conn.execute(
            sa.text("INSERT INTO src VALUES (:id, :num, :txt, :real_v)"),
            rows,
        )
    yield engine
    engine.dispose()


def _segments(engine, dialect: SQLDialect, key: str, npartitions: int):
    return build_range_segments(
        engine=engine,
        dialect=dialect,
        cte_prefix_sql=None,
        relation_sql=RELATION,
        key_sql=f'"{key}"',
        npartitions=npartitions,
    )


@pytest.mark.parametrize(
    "source",
    [ClickHouseDialect(), MssqlDialect(), MySQLDialect(), OracleDialect()],
    ids=lambda dialect: dialect.name,
)
@pytest.mark.parametrize("key", ["num", "txt", "real_v", "id"])
@pytest.mark.parametrize("npartitions", [1, 3, 7, 64, 2000])
def test_single_query_boundaries_match_offset_loop(engine, source, key, npartitions):
    offset_segments, offset_divisions, *_, offset_status = _segments(
        engine, SqliteDialect(), key, npartitions
    )
    single_segments, single_divisions, *_, single_status = _segments(
        engine, _SingleQuerySqlite(source), key, npartitions
    )

    assert offset_status == "offset_loop"
    assert single_status == "single_query"
    assert [segment.predicate_sql for segment in single_segments] == [
        segment.predicate_sql for segment in offset_segments
    ]
    assert single_divisions == offset_divisions


def test_single_query_runs_one_statement(engine, monkeypatch):
    statements: list[str] = []
    original = boundaries_module.query_df

    def counting_query_df(engine_, sql):
        statements.append(sql)
        return original(engine_, sql)

    monkeypatch.setattr(boundaries_module, "query_df", counting_query_df)
    segments, *_ = _segments(engine, _SingleQuerySqlite(MssqlDialect()), "num", 64)

    # query_row_stats and the boundaries statement; no per-boundary OFFSET query.
    assert len(statements) == 2
    assert len(segments) > 10


def test_failed_single_query_falls_back_to_offset_loop(engine, caplog):
    expected, expected_divisions, *_ = _segments(engine, SqliteDialect(), "txt", 16)

    with caplog.at_level("WARNING", logger=boundaries_module.__name__):
        segments, divisions, *_, status = _segments(engine, _BrokenSingleQuerySqlite(), "txt", 16)

    assert status.startswith("offset_loop(single query failed: ")
    assert [segment.predicate_sql for segment in segments] == [
        segment.predicate_sql for segment in expected
    ]
    assert divisions == expected_divisions
    assert "falling back to one query per boundary" in caplog.text


def test_empty_single_query_result_falls_back(engine, monkeypatch):
    original = boundaries_module.query_df

    def empty_boundaries(engine_, sql):
        df = original(engine_, sql)
        return df.iloc[0:0] if "dvt_rn" in sql else df

    monkeypatch.setattr(boundaries_module, "query_df", empty_boundaries)
    _, _, *_, status = _segments(engine, _SingleQuerySqlite(MySQLDialect()), "num", 8)

    assert status == "offset_loop(single query failed: ReadV3PlanningError)"


def test_table_plan_reports_boundary_method(engine):
    plan = resolve_planner(mode="table").build_plan(
        engine=engine,
        table_name="src",
        columns=["id", "num"],
        partition_col="id",
        partition_grouping={"mode": "range"},
        npartitions=4,
        **STRICT_PARTITIONING_KWARGS,
    )

    assert "range_boundaries=offset_loop" in plan.extra_warnings


def test_base_dialect_has_no_single_statement():
    with pytest.raises(NotImplementedError):
        SqliteDialect().range_boundaries_query(RELATION, "k", page_size=10, non_null_rows=100)


def test_clickhouse_boundaries_sql_uses_one_window_sort():
    sql = ClickHouseDialect().range_boundaries_query(
        "FROM `db`.`t`", "`k`", page_size=250, non_null_rows=1000
    )

    assert sql == (
        "SELECT boundary_value FROM (SELECT `k` AS boundary_value, "
        "row_number() OVER (ORDER BY `k` ASC ROWS BETWEEN CURRENT ROW AND CURRENT ROW) AS dvt_rn "
        "FROM `db`.`t` WHERE `k` IS NOT NULL) dvt_ranked "
        "WHERE (dvt_rn - 1) % 250 = 0 ORDER BY dvt_rn"
    )


def test_mssql_boundaries_sql_uses_modulo_operator():
    sql = MssqlDialect().range_boundaries_query(
        "FROM [dbo].[t]", "[k]", page_size=7, non_null_rows=50
    )

    assert "ROW_NUMBER() OVER (ORDER BY [k] ASC) AS dvt_rn" in sql
    assert "WHERE (dvt_rn - 1) % 7 = 0 ORDER BY dvt_rn" in sql
    assert "MOD(" not in sql


@pytest.mark.parametrize("dialect", [MySQLDialect(), OracleDialect()], ids=lambda d: d.name)
def test_mod_dialects_use_row_number_sql(dialect):
    sql = dialect.range_boundaries_query("FROM t", "k", page_size=3, non_null_rows=10)

    assert sql == (
        "SELECT boundary_value FROM (SELECT k AS boundary_value, "
        "ROW_NUMBER() OVER (ORDER BY k ASC) AS dvt_rn FROM t WHERE k IS NOT NULL) dvt_ranked "
        "WHERE MOD(dvt_rn - 1, 3) = 0 ORDER BY dvt_rn"
    )


def test_postgres_boundaries_sql_uses_percentile_disc():
    sql = PostgresDialect().range_boundaries_query(
        'FROM "public"."t"', '"k"', page_size=4, non_null_rows=10
    )

    assert sql == (
        "SELECT dvt_b.boundary_value FROM (SELECT percentile_disc("
        "ARRAY[0.05, 0.45, 0.85]::double precision[]) "
        'WITHIN GROUP (ORDER BY "k") AS dvt_bounds FROM "public"."t" '
        'WHERE "k" IS NOT NULL) dvt_q '
        "CROSS JOIN LATERAL unnest(dvt_q.dvt_bounds) WITH ORDINALITY "
        "AS dvt_b(boundary_value, dvt_ord) ORDER BY dvt_b.dvt_ord"
    )


@pytest.mark.parametrize(
    ("non_null_rows", "page_size"),
    [
        (1, 1),
        (10, 3),
        (997, 2),
        (5_000_000, 78_125),
        (49_690_000, 82_817),
        (49_690_000, 9_938),
        (5_000_000_000, 1_000_003),
    ],
)
def test_postgres_fractions_select_the_offset_rank(non_null_rows, page_size):
    # percentile_disc picks 1-based row max(1, ceil(f * N)); OFFSET r reads 1-based row r + 1.
    ranks = list(range(0, non_null_rows, page_size))
    sql = PostgresDialect().range_boundaries_query(
        "FROM t", "k", page_size=page_size, non_null_rows=non_null_rows
    )
    fractions = [float(value) for value in re.search(r"ARRAY\[(.*?)\]", sql).group(1).split(", ")]

    assert len(fractions) == len(ranks)
    for rank, fraction in zip(ranks, fractions, strict=True):
        assert max(1, math.ceil(fraction * non_null_rows)) == rank + 1


@pytest.mark.parametrize("key", ["num", "txt", "real_v"])
def test_single_query_keeps_scalar_types_of_offset_queries(engine, key):
    with engine.connect() as conn:
        non_null_rows = conn.exec_driver_sql(f"SELECT COUNT({key}) FROM src").scalar()
    kwargs = {
        "engine": engine,
        "cte_prefix_sql": None,
        "relation_sql": RELATION,
        "key_sql": key,
        "page_size": 37,
        "non_null_rows": non_null_rows,
    }
    offset_values, _ = boundaries_module.query_range_boundaries(dialect=SqliteDialect(), **kwargs)
    single_values, status = boundaries_module.query_range_boundaries(
        dialect=_SingleQuerySqlite(MssqlDialect()), **kwargs
    )

    assert status == "single_query"
    assert single_values == offset_values
    assert [type(value) for value in single_values] == [type(value) for value in offset_values]


# 2**53 + 3 is the smallest Int64 key that float64 rounds up (to 2**53 + 4).
BIG_BOUNDS = [2**53 + 3 + rank for rank in (0, 250, 500, 750, 999)]


def _int64_key_frames(sql: str, count_dtype: str) -> pd.DataFrame:
    """Result frames of an Int64 key next to UInt64 (clickhouse_connect) or Int64 counts."""
    if "min_v" in sql:
        return pd.DataFrame(
            {
                "min_v": np.array([BIG_BOUNDS[0]], dtype="int64"),
                "max_v": np.array([BIG_BOUNDS[-1]], dtype="int64"),
                "total_rows": np.array([1000], dtype=count_dtype),
                "non_null_rows": np.array([1000], dtype=count_dtype),
            }
        )
    return pd.DataFrame({"boundary_value": np.array(BIG_BOUNDS[:-1], dtype="int64")})


@pytest.mark.parametrize(
    ("dialect", "count_dtype"),
    [(ClickHouseDialect(), "uint64"), (PostgresDialect(), "int64")],
    ids=["clickhouse", "postgresql"],
)
def test_int64_key_renders_integer_literals_on_both_ends(monkeypatch, dialect, count_dtype):
    monkeypatch.setattr(
        boundaries_module, "query_df", lambda _engine, sql: _int64_key_frames(sql, count_dtype)
    )

    segments, divisions, *_ = build_range_segments(
        engine=None,
        dialect=dialect,
        cte_prefix_sql=None,
        relation_sql="FROM t",
        key_sql="k",
        npartitions=4,
    )

    # Exact integers: no quoted numbers, no float min/max rounded past the first or last row.
    assert [segment.predicate_sql for segment in segments] == [
        f"k >= {BIG_BOUNDS[0]} AND k < {BIG_BOUNDS[1]}",
        f"k >= {BIG_BOUNDS[1]} AND k < {BIG_BOUNDS[2]}",
        f"k >= {BIG_BOUNDS[2]} AND k < {BIG_BOUNDS[3]}",
        f"k >= {BIG_BOUNDS[3]} AND k <= {BIG_BOUNDS[4]}",
    ]
    assert divisions == tuple(BIG_BOUNDS)


def _numeric_key_frames(sql: str) -> pd.DataFrame:
    """A numeric key through psycopg: Decimal values in object columns."""
    if "min_v" in sql:
        return pd.DataFrame(
            {
                "min_v": [Decimal("10")],
                "max_v": [Decimal("40")],
                "total_rows": [4],
                "non_null_rows": [4],
            }
        )
    return pd.DataFrame(
        {"boundary_value": [Decimal(value) for value in ("10", "20.00", "30", "40")]}
    )


@pytest.mark.parametrize(
    ("integer_key", "expected_predicates", "expected_divisions"),
    [
        # numeric(18, 0): integral bounds render and divide as integers.
        (
            True,
            ["k >= 10 AND k < 20", "k >= 20 AND k < 30", "k >= 30 AND k <= 40"],
            (10, 20, 30, 40),
        ),
        # A fractional numeric key keeps its exact Decimal bounds.
        (
            False,
            ["k >= '10' AND k < '20.00'", "k >= '20.00' AND k < '30'", "k >= '30' AND k <= '40'"],
            (Decimal("10"), Decimal("20"), Decimal("30"), Decimal("40")),
        ),
    ],
    ids=["integer_key", "fractional_key"],
)
def test_integer_key_renders_integral_decimal_bounds_as_integers(
    monkeypatch, integer_key, expected_predicates, expected_divisions
):
    monkeypatch.setattr(
        boundaries_module, "query_df", lambda _engine, sql: _numeric_key_frames(sql)
    )

    segments, divisions, *_ = build_range_segments(
        engine=None,
        dialect=PostgresDialect(),
        cte_prefix_sql=None,
        relation_sql="FROM t",
        key_sql="k",
        npartitions=4,
        integer_key=integer_key,
    )

    assert [segment.predicate_sql for segment in segments] == expected_predicates
    assert divisions == expected_divisions
    assert [type(value) for value in divisions] == [type(value) for value in expected_divisions]
