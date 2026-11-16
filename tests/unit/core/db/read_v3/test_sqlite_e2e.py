from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy import text

from core.db.read_v3.dask import frame_from_executor
from core.db.read_v3.errors import ReadV3ConfigError, ReadV3ExecutionError, ReadV3PlanningError
from core.db.read_v3.models import PartitionStrategy, ValueKind
from core.db.read_v3.resolver import resolve_executor, resolve_planner
from core.metadata import get_df_metadata
from core.utils.dataframe_index import get_physical_index

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
    assert ddf.index.name == "__dvt_partition_key"
    assert get_physical_index(ddf).bound_column == "id"
    metadata_by_name = {column.name: column for column in get_df_metadata(ddf).columns}
    assert metadata_by_name["id"].index is False
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
    assert ddf.index.name == "__dvt_partition_bucket"
    assert get_physical_index(ddf).source_column == "category"
    assert get_physical_index(ddf).bound_column is None
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
    assert ddf.index.name == "__dvt_partition_key"
    assert get_physical_index(ddf).bound_column == "created_at"
    result = ddf.compute()
    assert len(result) == 100


def test_query_mode_keeps_business_column_that_collides_with_index_name(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'query_collision.sqlite'}")
    _seed(engine)
    plan = resolve_planner(mode="query").build_plan(
        engine=engine,
        query="SELECT id, value AS __dvt_partition_key FROM read_v3_test",
        columns=["__dvt_partition_key"],
        partition_col="id",
        npartitions=3,
        **STRICT_PARTITIONING_KWARGS,
    )
    ddf = frame_from_executor(resolve_executor(engine), plan)

    assert ddf.index.name == "__dvt_partition_key_1"
    assert get_physical_index(ddf).bound_column is None
    result = ddf.compute()
    assert result.columns.tolist() == ["__dvt_partition_key"]
    assert result.index.tolist() == list(range(1, 101))
    assert result["__dvt_partition_key"].iloc[-1] == 150


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
    assert ddf.index.name == "__dvt_partition_bucket"
    assert get_physical_index(ddf).bound_column is None


def _seed_grouped_categories(engine: sa.Engine, groups: list[tuple[str | None, int]]) -> int:
    rows = []
    for category, count in groups:
        for _ in range(count):
            rows.append({"id": len(rows) + 1, "category": category, "value": float(len(rows))})

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS read_v3_split_test"))
        conn.execute(
            text(
                """
                CREATE TABLE read_v3_split_test (
                    id INTEGER PRIMARY KEY,
                    category TEXT,
                    value REAL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO read_v3_split_test (id, category, value)
                VALUES (:id, :category, :value)
                """
            ),
            rows,
        )
    return len(rows)


# SQLite hash_expr buckets by text length: lengths 2..9 spread evenly over 4 buckets.
_OVERSIZED_PREFIX_GROUPS: list[tuple[str | None, int]] = [
    *((f"al{'x' * extra}", 40) for extra in range(8)),
    ("beta", 20),
    (None, 5),
]


def _build_oversized_prefix_plan(engine: sa.Engine, mode: str):
    planner = resolve_planner(mode=mode)
    common_kwargs = {
        "engine": engine,
        "columns": ["id", "category", "value"],
        "partition_col": "category",
        "partition_grouping": {"mode": "prefix", "length": 2},
        "npartitions": 4,
        "max_rows_per_partition": 100,
        **STRICT_PARTITIONING_KWARGS,
    }
    if mode == "table":
        return planner.build_plan(table_name="read_v3_split_test", **common_kwargs)
    return planner.build_plan(
        query="SELECT id, category, value FROM read_v3_split_test",
        **common_kwargs,
    )


@pytest.mark.parametrize("mode", ["table", "query"])
def test_partition_grouping_splits_oversized_prefix_group_by_key_hash(tmp_path, mode: str) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / f'grouping_split_{mode}.sqlite'}")
    total_rows = _seed_grouped_categories(engine, _OVERSIZED_PREFIX_GROUPS)

    plan = _build_oversized_prefix_plan(engine, mode)

    assert [segment.label for segment in plan.segments] == [
        "al#0/4",
        "al#1/4",
        "al#2/4",
        "al#3/4",
        "be",
        "__null__",
    ]
    assert [segment.expected_rows for segment in plan.segments] == [80, 80, 80, 80, 20, 5]
    assert plan.divisions == tuple(range(7))

    executor = resolve_executor(engine)
    sub_segment_rows = [len(executor.load_partition(plan, segment)) for segment in plan.segments[:4]]
    assert sub_segment_rows == [80, 80, 80, 80]

    ddf = frame_from_executor(executor, plan)
    result = ddf.compute().sort_values("id").reset_index(drop=True)
    assert ddf.known_divisions is True
    assert result["id"].tolist() == list(range(1, total_rows + 1))


def test_partition_grouping_rejects_oversized_null_group_before_reading(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'grouping_split_null.sqlite'}")
    _seed_grouped_categories(engine, [("alpha", 30), (None, 150)])

    with pytest.raises(
        ReadV3PlanningError,
        match=r"max_rows_per_partition=100 that cannot be split: '__null__' with 150 rows",
    ):
        _build_oversized_prefix_plan(engine, "table")


def test_partition_grouping_identical_values_still_fail_at_execution_with_label(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'grouping_split_same_value.sqlite'}")
    _seed_grouped_categories(engine, [("al", 150), ("beta", 10)])

    plan = _build_oversized_prefix_plan(engine, "table")
    assert [segment.label for segment in plan.segments] == ["al#0/2", "al#1/2", "be"]

    executor = resolve_executor(engine)
    with pytest.raises(
        ReadV3ExecutionError,
        match=r"Segment 'al#0/2' exceeded max_rows_per_partition=100 \(rows_read=101\)",
    ):
        executor.load_partition(plan, plan.segments[0])


def test_partition_grouping_rejects_oversized_as_is_value_before_reading(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'grouping_split_as_is.sqlite'}")
    _seed_grouped_categories(engine, [("alpha", 150), ("beta", 30)])

    with pytest.raises(
        ReadV3PlanningError,
        match=(
            r"mode='as_is' produced segments above max_rows_per_partition=100 that cannot be "
            r"split: 'alpha' with 150 rows \(a single key value cannot be spread by hashing\)"
        ),
    ):
        resolve_planner(mode="table").build_plan(
            engine=engine,
            table_name="read_v3_split_test",
            columns=["id", "category", "value"],
            partition_col="category",
            partition_grouping={"mode": "as_is"},
            npartitions=4,
            max_rows_per_partition=100,
            **STRICT_PARTITIONING_KWARGS,
        )
