from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import sqlalchemy as sa

from core.db.read_v3._auto_partition import AutoPartitionEstimate
from core.db.read_v3.dialects.clickhouse import ClickHouseDialect
from core.db.read_v3.models import PartitionStrategy, ReadSegment, SegmentDivision, ValueKind
from core.db.read_v3.planner.query import QueryReadPlanner
from core.db.read_v3.planner.table import TableReadPlanner

import config


STRICT_PARTITIONING_KWARGS = {
    "min_rows_per_partition": config.DASK_PARTITIONING.MIN_ROWS_PER_PART,
    "target_partition_mem_mb": config.DASK_PARTITIONING.TARGET_PARTITION_MEM_MB,
    "partitioning_overhead_coef": config.DASK_PARTITIONING.OVERHEAD_COEF,
    "max_partitions": config.DASK_PARTITIONING.MAX_PARTITIONS,
}


class _FakeDialect:
    name = "sqlite"

    def normalize_reflected_identifier(self, ident: str) -> str:
        return ident

    def quote_ident(self, ident: str) -> str:
        return ident

    def quote_result_column(self, ident: str) -> str:
        return ident

    def output_select_expr(
        self,
        expr_sql: str,
        *,
        output_name: str,
        type_repr: str = "",
    ) -> str:
        return f"{expr_sql} AS {self.quote_result_column(output_name)}"

    def requires_string_output_cast(self, type_repr: str) -> bool:
        return False

    def limit_offset(self, limit: int, offset: int) -> str:
        return f"LIMIT {limit} OFFSET {offset}"

    def full_table_name(self, table: str, schema: str | None) -> str:
        return f"{schema}.{table}" if schema else table

    def detect_value_kind(self, type_repr: str) -> ValueKind:
        raw = type_repr.lower()
        if "int" in raw:
            return ValueKind.NUMERIC
        return ValueKind.STRING

    def hash_expr(self, key_sql: str, buckets: int) -> str:
        return f"hash({key_sql}, {buckets})"


class _Inspector:
    def get_columns(self, *_args, **_kwargs):
        return [
            {"name": "id", "type": sa.Integer()},
            {"name": "payload", "type": sa.Text()},
        ]

    def get_pk_constraint(self, *_args, **_kwargs):
        return {"constrained_columns": ["id"]}


class _QuotedClickHouseInspector:
    def get_columns(self, *_args, **_kwargs):
        return [
            {"name": "Наименование товара", "type": sa.Text()},
            {"name": "Номер кассы", "type": sa.Integer()},
        ]

    def get_pk_constraint(self, *_args, **_kwargs):
        return {"constrained_columns": ["`Наименование товара`"]}


def _single_range_segment(*_args, **_kwargs):
    return (
        [
            ReadSegment(
                label="range_0",
                predicate_sql="id >= 1 AND id <= 20",
                order_by_sql="ORDER BY id ASC",
                division=SegmentDivision(start=1, end=20, include_end=True),
                strategy=PartitionStrategy.RANGE,
            )
        ],
        (1, 20),
        20,
        20,
    )


def test_table_planner_uses_auto_estimator_when_npartitions_is_missing(monkeypatch) -> None:
    captured: dict[str, int] = {}

    def _capture_range_segments(**kwargs):
        captured["npartitions"] = kwargs["npartitions"]
        return _single_range_segment()

    monkeypatch.setattr("core.db.read_v3.planner.table.inspect", lambda _engine: _Inspector())
    monkeypatch.setattr("core.db.read_v3.planner.table.resolve_dialect", lambda _engine: _FakeDialect())
    monkeypatch.setattr(
        "core.db.read_v3.planner.table.query_row_stats",
        lambda **_kwargs: (1, 20, 20, 20),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.table.estimate_table_partitions",
        lambda **_kwargs: AutoPartitionEstimate(
            npartitions=7,
            rows_per_part=10_000,
            bytes_per_row_est=128,
            effective_rows_est=20,
            effective_bytes_est=2_560,
            dialect="sqlite",
        ),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.table.choose_partition_strategy",
        lambda **_kwargs: SimpleNamespace(strategy=PartitionStrategy.RANGE, reason="test"),
    )
    monkeypatch.setattr("core.db.read_v3.planner.table.build_range_segments", _capture_range_segments)

    plan = TableReadPlanner().build_plan(
        engine=object(),
        table_name="events",
        columns=["id", "payload"],
        npartitions=None,
        **STRICT_PARTITIONING_KWARGS,
    )

    assert captured["npartitions"] == 7
    assert plan.npartitions == 7


def test_table_planner_keeps_explicit_npartitions_priority(monkeypatch) -> None:
    captured: dict[str, int] = {}

    def _capture_range_segments(**kwargs):
        captured["npartitions"] = kwargs["npartitions"]
        return _single_range_segment()

    monkeypatch.setattr("core.db.read_v3.planner.table.inspect", lambda _engine: _Inspector())
    monkeypatch.setattr("core.db.read_v3.planner.table.resolve_dialect", lambda _engine: _FakeDialect())
    monkeypatch.setattr(
        "core.db.read_v3.planner.table.query_row_stats",
        lambda **_kwargs: (1, 20, 20, 20),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.table.estimate_table_partitions",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("auto estimator must not be used")),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.table.choose_partition_strategy",
        lambda **_kwargs: SimpleNamespace(strategy=PartitionStrategy.RANGE, reason="test"),
    )
    monkeypatch.setattr("core.db.read_v3.planner.table.build_range_segments", _capture_range_segments)

    plan = TableReadPlanner().build_plan(
        engine=object(),
        table_name="events",
        columns=["id", "payload"],
        npartitions=4,
        **STRICT_PARTITIONING_KWARGS,
    )

    assert captured["npartitions"] == 4
    assert plan.npartitions == 4


def test_table_planner_normalizes_quoted_clickhouse_reflected_primary_key(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.db.read_v3.planner.table.inspect",
        lambda _engine: _QuotedClickHouseInspector(),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.table.resolve_dialect",
        lambda _engine: ClickHouseDialect(),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.table.query_row_stats",
        lambda **_kwargs: ("A", "Z", 20, 20),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.table.choose_partition_strategy",
        lambda **_kwargs: SimpleNamespace(strategy=PartitionStrategy.RANGE, reason="test"),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.table.build_range_segments",
        lambda **_kwargs: _single_range_segment(),
    )

    plan = TableReadPlanner().build_plan(
        engine=object(),
        table_name="sales",
        schema="DVT_Test",
        columns=["Наименование товара", "Номер кассы"],
        npartitions=1,
        **STRICT_PARTITIONING_KWARGS,
    )

    assert plan.partition_key_name == "Наименование товара"
    assert plan.partition_key_sql_name == "Наименование товара"


def test_query_planner_uses_auto_estimator_instead_of_legacy_infer(monkeypatch) -> None:
    captured: dict[str, int] = {}

    monkeypatch.setattr("core.db.read_v3.planner.query.resolve_dialect", lambda _engine: _FakeDialect())
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.build_read_v3_query_embedding",
        lambda *_args, **_kwargs: SimpleNamespace(cte_prefix_sql="", relation_sql="FROM user_query"),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.read_sql_df",
        lambda _engine, sql: pd.DataFrame(columns=["id", "payload"])
        if "WHERE 1=0" in str(sql)
        else pd.DataFrame({"sample_value": [1]}),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.describe_query_columns",
        lambda *_args, **_kwargs: [("id", "INTEGER"), ("payload", "TEXT")],
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.query_row_stats",
        lambda **_kwargs: (1, 20, 20, 20),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.infer_npartitions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("infer_npartitions must not be used")),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.estimate_query_partitions",
        lambda **_kwargs: AutoPartitionEstimate(
            npartitions=5,
            rows_per_part=10_000,
            bytes_per_row_est=256,
            effective_rows_est=20,
            effective_bytes_est=5_120,
            dialect="sqlite",
        ),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.choose_partition_strategy",
        lambda **_kwargs: SimpleNamespace(strategy=PartitionStrategy.HASH, reason="test"),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.build_hash_segments",
        lambda **kwargs: (
            captured.setdefault("npartitions", kwargs["npartitions"]),
            [
                ReadSegment(
                    label="bucket_0",
                    predicate_sql="hash(id, 5) = 0",
                    order_by_sql="ORDER BY hash(id, 5) ASC, id ASC",
                    division=SegmentDivision(start=0, end=1, include_end=True),
                    strategy=PartitionStrategy.HASH,
                )
            ],
            (0, 1),
            1,
        )[1:],
    )

    plan = QueryReadPlanner().build_plan(
        engine=object(),
        query="SELECT id, payload FROM events",
        partition_col="id",
        npartitions=None,
        **STRICT_PARTITIONING_KWARGS,
    )

    assert captured["npartitions"] == 5
    assert plan.npartitions == 5


def test_query_planner_hash_grouping_override_beats_auto_estimator(monkeypatch) -> None:
    captured: dict[str, int] = {}

    monkeypatch.setattr("core.db.read_v3.planner.query.resolve_dialect", lambda _engine: _FakeDialect())
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.build_read_v3_query_embedding",
        lambda *_args, **_kwargs: SimpleNamespace(cte_prefix_sql="", relation_sql="FROM user_query"),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.read_sql_df",
        lambda _engine, sql: pd.DataFrame(columns=["id", "payload"])
        if "WHERE 1=0" in str(sql)
        else pd.DataFrame({"sample_value": [1]}),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.describe_query_columns",
        lambda *_args, **_kwargs: [("id", "INTEGER"), ("payload", "TEXT")],
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.query_row_stats",
        lambda **_kwargs: (1, 20, 20, 20),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.estimate_query_partitions",
        lambda **_kwargs: AutoPartitionEstimate(
            npartitions=9,
            rows_per_part=10_000,
            bytes_per_row_est=256,
            effective_rows_est=20,
            effective_bytes_est=5_120,
            dialect="sqlite",
        ),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.choose_partition_strategy",
        lambda **_kwargs: SimpleNamespace(strategy=PartitionStrategy.HASH, reason="test"),
    )
    monkeypatch.setattr(
        "core.db.read_v3.planner.query.build_hash_segments",
        lambda **kwargs: (
            captured.setdefault("npartitions", kwargs["npartitions"]),
            [
                ReadSegment(
                    label="bucket_0",
                    predicate_sql="hash(id, 3) = 0",
                    order_by_sql="ORDER BY hash(id, 3) ASC, id ASC",
                    division=SegmentDivision(start=0, end=1, include_end=True),
                    strategy=PartitionStrategy.HASH,
                )
            ],
            (0, 1),
            1,
        )[1:],
    )

    plan = QueryReadPlanner().build_plan(
        engine=object(),
        query="SELECT id, payload FROM events",
        partition_col="id",
        npartitions=None,
        partition_grouping={"mode": "hash", "buckets": 3},
        **STRICT_PARTITIONING_KWARGS,
    )

    assert captured["npartitions"] == 3
    assert plan.npartitions == 3
