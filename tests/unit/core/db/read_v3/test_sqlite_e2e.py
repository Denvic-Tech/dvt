from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.errors import ReadV3ConfigError, ReadV3PlanningError
from core.db.read_v3.models import PartitionStrategy, ValueKind
from core.db.read_v3.resolver import resolve_executor, resolve_planner
from core.metadata import get_df_metadata

import config

STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}


def _seed(engine: sa.Engine) -> None:
    rows = []
    base_ts = datetime(2026, 1, 1, 0, 0, 0)
    values = ["alpha", "beta", None, "gamma", "delta"]
    for idx in range(1, 101):
        rows.append(
            {
                "id": idx,
                "category": values[idx % len(values)],
                "created_at": base_ts + timedelta(minutes=idx),
                "value": float(idx) * 1.5,
                "is_active": None if idx % 10 == 0 else (idx % 2 == 0),
            }
        )

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_test (
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
                INSERT INTO read_v3_test (id, category, created_at, value, is_active)
                VALUES (:id, :category, :created_at, :value, :is_active)
                """
            ),
            rows,
        )


def test_table_mode_range_produces_known_divisions(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'table_range.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_test",
        columns=["id", "category", "value"],
        partition_col="id",
        npartitions=8,
        **STRICT_PARTITIONING_KWARGS,
    )
    assert plan.strategy == PartitionStrategy.RANGE

    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)

    assert ddf.known_divisions is True
    assert "id" in ddf.columns
    assert ddf.index.name == "id"
    metadata_by_name = {column.name: column for column in get_df_metadata(ddf).columns}
    assert metadata_by_name["id"].index is True
    result = ddf.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert len(result) == 100
    assert result.iloc[0]["id"] == 1
    assert result.iloc[-1]["id"] == 100


def test_table_mode_nullable_key_selects_hash(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'table_hash.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_test",
        columns=["id", "category", "value"],
        partition_col="category",
        npartitions=6,
        **STRICT_PARTITIONING_KWARGS,
    )
    assert plan.strategy == PartitionStrategy.HASH

    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)

    assert ddf.known_divisions is True
    assert len(ddf.compute()) == 100


def test_query_mode_requires_partition_col(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'query.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="query")
    with pytest.raises(ReadV3ConfigError):
        planner.build_plan(
            engine=engine,
            query="SELECT id, category, created_at, value FROM read_v3_test",
            partition_col=None,
            npartitions=4,
            **STRICT_PARTITIONING_KWARGS,
        )


def test_query_mode_range_by_datetime(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'query_range.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="query")
    plan = planner.build_plan(
        engine=engine,
        query="SELECT id, category, created_at, value FROM read_v3_test",
        partition_col="created_at",
        npartitions=5,
        **STRICT_PARTITIONING_KWARGS,
    )

    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)

    assert ddf.known_divisions is True
    result = ddf.compute()
    assert len(result) == 100


def test_table_mode_limit_preserves_known_divisions(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'table_limit.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_test",
        columns=["id", "category", "value"],
        partition_col="id",
        npartitions=6,
        limit=17,
        **STRICT_PARTITIONING_KWARGS,
    )

    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)

    assert ddf.known_divisions is True
    result = ddf.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert len(result) == 17
    assert result["id"].tolist() == list(range(1, 18))


def test_query_mode_limit_preserves_known_divisions(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'query_limit.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="query")
    plan = planner.build_plan(
        engine=engine,
        query="SELECT id, category, created_at, value FROM read_v3_test",
        partition_col="id",
        npartitions=5,
        limit=23,
        **STRICT_PARTITIONING_KWARGS,
    )

    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)

    assert ddf.known_divisions is True
    result = ddf.compute().reset_index(drop=True).sort_values("id").reset_index(drop=True)
    assert len(result) == 23
    assert result["id"].tolist() == list(range(1, 24))


def test_table_mode_rejects_non_positive_limit(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'table_bad_limit.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="table")
    with pytest.raises(ReadV3ConfigError, match="limit must be positive"):
        planner.build_plan(
            engine=engine,
            table_name="read_v3_test",
            columns=["id"],
            partition_col="id",
            npartitions=2,
            limit=0,
            **STRICT_PARTITIONING_KWARGS,
        )


def test_query_mode_rejects_non_positive_limit(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'query_bad_limit.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="query")
    with pytest.raises(ReadV3ConfigError, match="limit must be positive"):
        planner.build_plan(
            engine=engine,
            query="SELECT id, category, created_at, value FROM read_v3_test",
            partition_col="id",
            npartitions=2,
            limit=0,
            **STRICT_PARTITIONING_KWARGS,
        )


@pytest.mark.parametrize(
    ("partition_col", "partition_grouping"),
    [
        ("category", {"mode": "prefix", "length": 1}),
        ("value", {"mode": "step", "bins": 5}),
        ("created_at", {"mode": "granularity", "granularity": "day"}),
        ("is_active", {"mode": "as_is"}),
    ],
)
def test_table_mode_partition_grouping_supports_all_v2_kinds(
    tmp_path,
    partition_col: str,
    partition_grouping: dict[str, object],
) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / f'table_grouping_{partition_col}.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_test",
        columns=["id", "category", "created_at", "value", "is_active"],
        partition_col=partition_col,
        partition_grouping=partition_grouping,
        npartitions=6,
        **STRICT_PARTITIONING_KWARGS,
    )
    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)

    assert ddf.known_divisions is True
    result = ddf.compute().sort_values("id").reset_index(drop=True)
    assert len(result) == 100
    assert result["id"].tolist() == list(range(1, 101))


def test_query_mode_partition_grouping_string_explicit_values(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'query_grouping_string.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="query")
    plan = planner.build_plan(
        engine=engine,
        query="SELECT id, category, created_at, value FROM read_v3_test",
        partition_col="category",
        partition_grouping={"mode": "explicit_values", "values": ["alpha", "beta", None], "other": True},
        npartitions=4,
        **STRICT_PARTITIONING_KWARGS,
    )
    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)

    assert ddf.known_divisions is True
    result = ddf.compute().sort_values("id").reset_index(drop=True)
    assert len(result) == 100
    assert result["id"].tolist() == list(range(1, 101))


def test_query_mode_rejects_unknown_output_kind_when_column_is_always_null(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'query_unknown_kind.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="query")
    with pytest.raises(
        ReadV3PlanningError,
        match=r"could not infer output column kinds in query mode.*query=.*unknown_col.*kind.*unknown",
    ):
        planner.build_plan(
            engine=engine,
            query="SELECT id, NULL AS unknown_col FROM read_v3_test",
            partition_col="id",
            npartitions=2,
            **STRICT_PARTITIONING_KWARGS,
        )


def test_table_mode_rejects_unknown_output_kind_for_blob_column(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'table_unknown_kind_blob.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_blob_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_blob_test (
                    id INTEGER PRIMARY KEY,
                    payload BLOB
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO read_v3_blob_test (id, payload)
                VALUES (1, X'0102')
                """
            )
        )

    planner = resolve_planner(mode="table")
    with pytest.raises(
        ReadV3PlanningError,
        match=r"could not infer output column kinds in table mode.*table='read_v3_blob_test'.*payload.*kind.*unknown",
    ):
        planner.build_plan(
            engine=engine,
            table_name="read_v3_blob_test",
            columns=["id", "payload"],
            partition_col="id",
            npartitions=2,
            **STRICT_PARTITIONING_KWARGS,
        )


def test_table_mode_accepts_json_output_column(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'table_json_output.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_json_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_json_test (
                    id INTEGER PRIMARY KEY,
                    payload JSON
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO read_v3_json_test (id, payload)
                VALUES (1, '{"alpha": 1}')
                """
            )
        )

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_json_test",
        columns=["id", "payload"],
        partition_col="id",
        npartitions=2,
        **STRICT_PARTITIONING_KWARGS,
    )
    assert plan.output_column_kinds["payload"] == ValueKind.JSON


def test_table_mode_rejects_json_partition_key(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'table_json_key.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_json_key_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_json_key_test (
                    id INTEGER PRIMARY KEY,
                    payload JSON
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO read_v3_json_key_test (id, payload)
                VALUES (1, '{"alpha": 1}')
                """
            )
        )

    planner = resolve_planner(mode="table")
    with pytest.raises(
        ReadV3PlanningError,
        match=r"does not support JSON partition keys in table mode.*column='payload'.*kind='json'.*type='JSON'",
    ):
        planner.build_plan(
            engine=engine,
            table_name="read_v3_json_key_test",
            columns=["id"],
            partition_col="payload",
            npartitions=2,
            **STRICT_PARTITIONING_KWARGS,
        )


def test_table_mode_rejects_unknown_partition_key_kind_for_blob_column(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'table_unknown_key_kind_blob.sqlite'}")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_blob_key_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_blob_key_test (
                    id INTEGER PRIMARY KEY,
                    payload BLOB
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO read_v3_blob_key_test (id, payload)
                VALUES (1, X'0102')
                """
            )
        )

    planner = resolve_planner(mode="table")
    with pytest.raises(
        ReadV3PlanningError,
        match=r"could not infer partition key kind in table mode.*table='read_v3_blob_key_test'.*column='payload'.*kind='unknown'.*type='BLOB'",
    ):
        planner.build_plan(
            engine=engine,
            table_name="read_v3_blob_key_test",
            columns=["id"],
            partition_col="payload",
            npartitions=2,
            **STRICT_PARTITIONING_KWARGS,
        )


def test_partition_grouping_supports_hash_mode(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'grouping_conflict.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_test",
        columns=["id", "category"],
        partition_col="category",
        partition_grouping={"mode": "hash", "buckets": 5},
        npartitions=3,
        **STRICT_PARTITIONING_KWARGS,
    )
    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)

    assert ddf.known_divisions is True
    result = ddf.compute().sort_values("id").reset_index(drop=True)
    assert len(result) == 100


def test_table_mode_rejects_unknown_selected_column(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'table_unknown_column.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="table")
    with pytest.raises(ReadV3PlanningError, match="was not found in table columns"):
        planner.build_plan(
            engine=engine,
            table_name="read_v3_test",
            columns=["id", "missing_column"],
            partition_col="id",
            npartitions=4,
            **STRICT_PARTITIONING_KWARGS,
        )


def test_query_mode_rejects_unknown_selected_column(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'query_unknown_column.sqlite'}")
    _seed(engine)

    planner = resolve_planner(mode="query")
    with pytest.raises(ReadV3PlanningError, match="was not found in query result columns"):
        planner.build_plan(
            engine=engine,
            query="SELECT id, category, created_at, value FROM read_v3_test",
            columns=["id", "missing_column"],
            partition_col="id",
            npartitions=4,
            **STRICT_PARTITIONING_KWARGS,
        )


def test_table_mode_partition_grouping_prefix_for_empty_table_builds_single_empty_segment(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'table_grouping_prefix_empty.sqlite'}")

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_empty_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_empty_test (
                    id INTEGER PRIMARY KEY,
                    category TEXT,
                    created_at DATETIME,
                    value REAL
                )
                """
            )
        )

    planner = resolve_planner(mode="table")
    plan = planner.build_plan(
        engine=engine,
        table_name="read_v3_empty_test",
        columns=["id", "category", "created_at", "value"],
        partition_col="category",
        partition_grouping={"mode": "prefix", "length": 1},
        npartitions=4,
        **STRICT_PARTITIONING_KWARGS,
    )

    assert plan.total_rows == 0
    assert len(plan.segments) == 1
    assert plan.segments[0].predicate_sql == "1=0"
    assert plan.divisions == (0, 1)

    executor = resolve_executor(engine)
    ddf = frame_from_executor(executor, plan)
    result = ddf.compute().reset_index(drop=True)

    assert ddf.known_divisions is True
    assert result.empty
    assert result.columns.tolist() == ["id", "category", "created_at", "value"]
