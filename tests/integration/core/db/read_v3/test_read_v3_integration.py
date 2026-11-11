from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy import text

from core.db.read_v3._auto_partition import (
    ROW_OVERHEAD_BYTES,
    TABLE_BPR_SAFETY_COEF,
    estimate_table_bytes_per_row,
)
from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.dialects.postgres import PostgresDialect
from core.db.read_v3.errors import ReadV3ExecutionError
from core.db.read_v3.planner.boundaries import query_range_boundaries
from core.db.read_v3.resolver import resolve_executor, resolve_planner

import config


STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}


def _seed(engine: sa.Engine, rows: int = 120) -> None:
    payload = []
    base_ts = datetime(2026, 1, 1, 0, 0, 0)
    categories = ["alpha", "beta", "gamma"]
    for idx in range(1, rows + 1):
        payload.append(
            {
                "id": idx,
                "category": categories[idx % len(categories)],
                "created_at": base_ts + timedelta(minutes=idx),
                "value": float(idx) * 2.0,
                "is_active": None if idx % 9 == 0 else (idx % 2 == 0),
            }
        )

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_integration_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_integration_test (
                    id INTEGER PRIMARY KEY,
                    category TEXT,
                    created_at DATETIME,
                    value REAL,
                    is_active BOOLEAN
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO read_v3_integration_test (id, category, created_at, value, is_active)
                VALUES (:id, :category, :created_at, :value, :is_active)
                """
            ),
            payload,
        )


def _seed_empty(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_integration_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_integration_test (
                    id INTEGER PRIMARY KEY,
                    category TEXT,
                    created_at DATETIME,
                    value REAL,
                    is_active BOOLEAN
                )
                """
            )
        )


def _seed_bool_like_strings(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_invalid_bool_cast_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_invalid_bool_cast_test (
                    id INTEGER PRIMARY KEY,
                    bool_col BOOLEAN
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO read_v3_invalid_bool_cast_test (id, bool_col)
                VALUES
                    (1, 'false'),
                    (2, 'true'),
                    (3, 1),
                    (4, 0),
                    (5, NULL)
                """
            )
        )


def _seed_invalid_bool_values(engine: sa.Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_invalid_bool_cast_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_invalid_bool_cast_test (
                    id INTEGER PRIMARY KEY,
                    bool_col BOOLEAN
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO read_v3_invalid_bool_cast_test (id, bool_col)
                VALUES
                    (1, 'false'),
                    (2, 'true'),
                    (3, 'not_bool')
                """
            )
        )


def test_read_v3_table_mode_limit_integration(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'read_v3_table_limit.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_integration_test",
        columns=["id", "category", "value"],
        partition_col="id",
        npartitions=7,
        limit=31,
        **STRICT_PARTITIONING_KWARGS,
    )
    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)

    assert ddf.known_divisions is True
    assert plan.total_rows == 31

    result = ddf.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert len(result) == 31
    assert result["id"].tolist() == list(range(1, 32))


def test_read_v3_query_mode_limit_integration(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'read_v3_query_limit.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="query")
    plan = planner.build_plan(
        engine=engine,
        query="SELECT id, category, created_at, value FROM read_v3_integration_test",
        partition_col="id",
        npartitions=6,
        limit=29,
        **STRICT_PARTITIONING_KWARGS,
    )
    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)

    assert ddf.known_divisions is True
    assert plan.total_rows == 29

    result = ddf.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert len(result) == 29
    assert result["id"].tolist() == list(range(1, 30))


def test_read_v3_table_mode_partition_grouping_bool_integration(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'read_v3_table_grouping_bool.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_integration_test",
        columns=["id", "category", "is_active"],
        partition_col="is_active",
        partition_grouping={"mode": "explicit_values", "values": [True, False, None], "other": False},
        npartitions=4,
        **STRICT_PARTITIONING_KWARGS,
    )
    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)

    assert ddf.known_divisions is True
    result = ddf.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert len(result) == 120
    assert result["id"].tolist() == list(range(1, 121))


def test_read_v3_query_mode_partition_grouping_numeric_integration(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'read_v3_query_grouping_numeric.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="query")
    plan = planner.build_plan(
        engine=engine,
        query="SELECT id, category, created_at, value FROM read_v3_integration_test",
        partition_col="value",
        partition_grouping={"mode": "ranges", "ranges": [[0, 80, False], [80, 200, False], [200, 1000, True]]},
        npartitions=5,
        **STRICT_PARTITIONING_KWARGS,
    )
    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)

    assert ddf.known_divisions is True
    result = ddf.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert len(result) == 120
    assert result["id"].tolist() == list(range(1, 121))


def test_read_v3_table_mode_partition_grouping_prefix_empty_table_integration(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'read_v3_table_grouping_prefix_empty.sqlite'}")
    _seed_empty(engine)

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_integration_test",
        columns=["id", "category", "created_at", "value"],
        partition_col="category",
        partition_grouping={"mode": "prefix", "length": 1},
        npartitions=4,
        **STRICT_PARTITIONING_KWARGS,
    )
    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)

    assert plan.total_rows == 0
    assert len(plan.segments) == 1
    assert plan.segments[0].predicate_sql == "1=0"
    assert plan.divisions == (0, 1)
    assert ddf.known_divisions is True

    result = ddf.compute().reset_index(drop=True)
    assert result.empty
    assert result.columns.tolist() == ["id", "category", "created_at", "value"]


def test_read_v3_table_mode_uses_string_dtype_for_string_columns_integration(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'read_v3_string_dtype_table.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_integration_test",
        columns=["id", "category"],
        partition_col="id",
        npartitions=3,
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
    assert result["category"].dtype.name == "string"
    assert result["category"].iloc[0] == "beta"
    assert result["category"].iloc[-1] == "alpha"


def test_read_v3_table_mode_parses_bool_like_strings_integration(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'read_v3_bool_cast_table.sqlite'}")
    _seed_bool_like_strings(engine)

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_invalid_bool_cast_test",
        columns=["id", "bool_col"],
        partition_col="id",
        npartitions=2,
        **STRICT_PARTITIONING_KWARGS,
    )
    executor = resolve_executor(engine)

    result = frame_from_executor(executor, plan).compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert result["bool_col"].dtype.name == "boolean"
    assert result["bool_col"].tolist() == [False, True, True, False, pd.NA]


def test_read_v3_table_mode_raises_on_invalid_bool_cast_integration(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'read_v3_bool_cast_table_invalid.sqlite'}")
    _seed_invalid_bool_values(engine)

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_invalid_bool_cast_test",
        columns=["id", "bool_col"],
        partition_col="id",
        npartitions=2,
        **STRICT_PARTITIONING_KWARGS,
    )
    executor = resolve_executor(engine)

    with pytest.raises(ReadV3ExecutionError, match="Failed to cast read_v3 column 'bool_col'"):
        frame_from_executor(executor, plan).compute()


def test_read_v3_query_mode_casts_bool_like_values_to_string_without_meta_mismatch_integration(
    tmp_path,
) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'read_v3_bool_cast_query.sqlite'}")
    _seed_bool_like_strings(engine)

    planner = resolve_planner(mode="query")
    plan = planner.build_plan(
        engine=engine,
        query="SELECT id, bool_col FROM read_v3_invalid_bool_cast_test",
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
    assert result["bool_col"].dtype.name == "string"
    values = result["bool_col"].tolist()
    assert values[:2] == ["false", "true"]
    assert values[2] in {"1", "1.0"}
    assert values[3] in {"0", "0.0"}
    assert pd.isna(values[4])


PG_BOUNDARY_ROWS = 30_000
PG_BOUNDARY_KEYS = ["k_int", "k_str", "k_dt", "k_dec", "n_int", "n_str", "n_dt", "n_dec"]


class _OffsetOnlyPostgresDialect(PostgresDialect):
    def range_boundaries_query(self, relation_sql, key_sql, *, page_size, non_null_rows):
        raise NotImplementedError


@pytest.fixture
def postgres_boundary_table(postgres_test_engine: sa.Engine):
    engine = postgres_test_engine
    table_name = f"rv3_bounds_{uuid4().hex[:8]}"
    # Duplicated keys in a physical order unrelated to the key order; NULLs in the n_* columns.
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE {table_name} AS
                SELECT g::bigint AS id,
                       ((g * 7919) % 4000 - 2000)::bigint AS k_int,
                       's' || ((g * 104729) % 2500) AS k_str,
                       timestamp '2024-01-01' + ((g * 31) % 3000) * interval '1 minute' AS k_dt,
                       (((g * 613) % 7000)::numeric / 3)::numeric(18, 4) AS k_dec,
                       CASE WHEN g % 17 = 0 THEN NULL ELSE ((g * 389) % 900)::bigint END AS n_int,
                       CASE WHEN g % 19 = 0 THEN NULL ELSE 'n' || ((g * 211) % 700) END AS n_str,
                       CASE WHEN g % 23 = 0 THEN NULL
                            ELSE timestamp '2020-01-01' + ((g * 17) % 800) * interval '1 hour'
                       END AS n_dt,
                       CASE WHEN g % 29 = 0 THEN NULL
                            ELSE (((g * 97) % 600)::numeric / 7)::numeric(18, 4)
                       END AS n_dec
                FROM generate_series(0::bigint, {PG_BOUNDARY_ROWS - 1}) AS g
                """
            )
        )
        conn.execute(text(f"ALTER TABLE {table_name} ADD PRIMARY KEY (id)"))
        conn.execute(text(f"ANALYZE {table_name}"))
    yield engine, table_name
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))


@pytest.mark.docker_required
@pytest.mark.parametrize("key", PG_BOUNDARY_KEYS)
def test_postgres_single_query_range_boundaries_match_offset_queries(
    postgres_boundary_table, key: str
) -> None:
    engine, table_name = postgres_boundary_table
    with engine.connect() as conn:
        non_null_rows = conn.execute(text(f"SELECT count({key}) FROM {table_name}")).scalar()
    for npartitions in (13, 64):
        kwargs = {
            "engine": engine,
            "cte_prefix_sql": None,
            "relation_sql": f'FROM "{table_name}"',
            "key_sql": f'"{key}"',
            "page_size": -(-non_null_rows // npartitions),
            "non_null_rows": non_null_rows,
        }
        single, single_status = query_range_boundaries(dialect=PostgresDialect(), **kwargs)
        offset, offset_status = query_range_boundaries(
            dialect=_OffsetOnlyPostgresDialect(), **kwargs
        )

        assert (single_status, offset_status) == ("single_query", "offset_loop")
        assert len(single) == len(range(0, non_null_rows, kwargs["page_size"]))
        assert single == offset, (key, npartitions)
        assert [type(value) for value in single] == [type(value) for value in offset]


@pytest.mark.docker_required
@pytest.mark.parametrize("key", ["k_int", "k_str", "k_dt", "k_dec"])
def test_postgres_single_query_range_plan_reads_every_row(
    postgres_boundary_table, key: str
) -> None:
    engine, table_name = postgres_boundary_table
    executor = resolve_executor(engine, max_concurrent_queries=4)
    table_plan = resolve_planner(mode="table").build_plan(
        engine=engine,
        table_name=table_name,
        partition_col=key,
        partition_grouping={"mode": "range"},
        npartitions=12,
        **STRICT_PARTITIONING_KWARGS,
    )
    query_plan = resolve_planner(mode="query").build_plan(
        engine=engine,
        query=f"SELECT id, {key} FROM {table_name} WHERE mod(id, 3) <> 1",
        partition_col=key,
        partition_grouping={"mode": "range"},
        npartitions=7,
        **STRICT_PARTITIONING_KWARGS,
    )

    for plan, expected_rows in (
        (table_plan, PG_BOUNDARY_ROWS),
        (query_plan, PG_BOUNDARY_ROWS - len(range(1, PG_BOUNDARY_ROWS, 3))),
    ):
        assert "range_boundaries=single_query" in plan.extra_warnings
        assert plan.segment_count > 1
        result = frame_from_executor(executor, plan).compute(scheduler="threads", num_workers=4)
        assert len(result) == expected_rows
        assert result["id"].nunique() == expected_rows


@pytest.mark.docker_required
def test_postgres_table_width_uses_pg_stats_without_schema(
    postgres_boundary_table, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, table_name = postgres_boundary_table
    monkeypatch.setattr(
        "core.db.read_v3._auto_partition._sample_table_rows",
        lambda *_args, **_kwargs: pytest.fail("pg_stats widths must be used"),
    )
    columns_info = sa.inspect(engine).get_columns(table_name)
    names = [str(column["name"]) for column in columns_info]
    with engine.connect() as conn:
        real = conn.execute(
            text(
                "SELECT "
                + " + ".join(f"coalesce(avg(pg_column_size({name})), 0)" for name in names)
                + f" FROM {table_name}"
            )
        ).scalar()

    estimate = estimate_table_bytes_per_row(
        engine=engine,
        dialect=PostgresDialect(),
        table_name=table_name,
        schema=None,
        selected_columns=names,
        columns_info=columns_info,
    )

    raw_width = (estimate - ROW_OVERHEAD_BYTES) / TABLE_BPR_SAFETY_COEF
    assert abs(raw_width - float(real)) <= 0.3 * float(real), (estimate, real)
