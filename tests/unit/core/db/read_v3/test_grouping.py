from __future__ import annotations

import pandas as pd
import pytest

from core.db.read_v3.dialects.base import SQLDialect
from core.db.read_v3.dialects.sqlite import SqliteDialect
from core.db.read_v3.errors import ReadV3PlanningError
from core.db.read_v3.grouping.models import (
    PartitionSegment as GroupingPartitionSegment,
    ValueKind as GroupingValueKind,
)
from core.db.read_v3.models import SegmentDivision, ValueKind
from core.db.read_v3.partitioning.grouping import V3GroupingHelper, build_grouping_segments


def test_value_counts_expr_groups_by_derived_column_alias(monkeypatch) -> None:
    helper = V3GroupingHelper(
        engine=object(),  # type: ignore[arg-type]
        dialect=SqliteDialect(),
        relation_sql="FROM user_query",
        cte_prefix_sql=None,
        value_kind=GroupingValueKind.STRING,
    )
    executed_sql: list[str] = []

    def fake_query_df(sql: str) -> pd.DataFrame:
        executed_sql.append(sql)
        if len(executed_sql) == 1:
            return pd.DataFrame({"v": ["o"], "cnt": [1]})
        return pd.DataFrame({"cnt": [0]})

    monkeypatch.setattr(helper, "_query_df", fake_query_df)

    result = helper.value_counts_expr('substr("table_code", 1, 1)', max_groups=4)

    assert result == [("o", 1)]
    assert executed_sql[0] == (
        'SELECT v, count(*) AS cnt '
        'FROM (SELECT substr("table_code", 1, 1) AS v FROM user_query) '
        "__dvt_group_values WHERE v IS NOT NULL "
        "GROUP BY v ORDER BY cnt DESC LIMIT 4 OFFSET 0"
    )


_NAME_SQL = '"name"'
_PREFIX_SQL = 'substr("name", 1, 2)'


def _build_with_groups(
    monkeypatch,
    legacy_segments: list[GroupingPartitionSegment],
    *,
    max_rows_per_partition: int,
    max_partitions: int = 5000,
    dialect: SQLDialect | None = None,
):
    monkeypatch.setattr(
        "core.db.read_v3.partitioning.grouping.build_custom_segments",
        lambda **_kwargs: legacy_segments,
    )
    return build_grouping_segments(
        engine=object(),  # type: ignore[arg-type]
        dialect=dialect or SqliteDialect(),
        relation_sql='FROM "products"',
        cte_prefix_sql=None,
        key_sql=_NAME_SQL,
        partition_key_name="name",
        value_kind=ValueKind.STRING,
        partition_grouping={"mode": "prefix", "length": 2},
        total_rows=sum(segment.count or 0 for segment in legacy_segments),
        npartitions=4,
        limit=None,
        partition_granularity=None,
        max_rows_per_partition=max_rows_per_partition,
        max_partitions=max_partitions,
    )


def _prefix_group(label: str, count: int) -> GroupingPartitionSegment:
    return GroupingPartitionSegment(
        label=label,
        include_values=[label],
        count=count,
        value_expr=_PREFIX_SQL,
    )


class _NoHashDialect(SqliteDialect):
    name = "nohash"

    def hash_expr(self, key_sql: str, buckets: int) -> str:
        raise NotImplementedError


def test_build_grouping_segments_splits_oversized_group_by_key_hash(monkeypatch) -> None:
    result = _build_with_groups(
        monkeypatch,
        [_prefix_group("Мо", 250), _prefix_group("Хл", 40)],
        max_rows_per_partition=100,
    )

    # floor(0.8 * 100) = 80 rows per sub-segment -> ceil(250 / 80) = 4 buckets of ceil(250 / 4).
    hash_sql = SqliteDialect().hash_expr(_NAME_SQL, 4)
    assert [segment.label for segment in result.segments] == [
        "Мо#0/4",
        "Мо#1/4",
        "Мо#2/4",
        "Мо#3/4",
        "Хл",
    ]
    assert [segment.predicate_sql for segment in result.segments] == [
        *(f"({_PREFIX_SQL} IN ('Мо')) AND {hash_sql} = {bucket}" for bucket in range(4)),
        f"{_PREFIX_SQL} IN ('Хл')",
    ]
    assert [segment.expected_rows for segment in result.segments] == [63, 63, 63, 63, 40]
    assert result.divisions == (0, 1, 2, 3, 4, 5)
    assert [segment.index_literal for segment in result.segments] == [0, 1, 2, 3, 4]
    assert [
        (segment.bucket_start, segment.bucket_end, segment.division)
        for segment in result.segments
    ] == [
        (idx, idx + 1, SegmentDivision(start=idx, end=idx + 1, include_end=True))
        for idx in range(5)
    ]


def test_build_grouping_segments_keeps_group_at_exact_ceiling(monkeypatch) -> None:
    result = _build_with_groups(
        monkeypatch,
        [_prefix_group("Мо", 100)],
        max_rows_per_partition=100,
    )

    assert [segment.label for segment in result.segments] == ["Мо"]
    assert result.segments[0].predicate_sql == f"{_PREFIX_SQL} IN ('Мо')"
    assert result.segments[0].expected_rows == 100
    assert result.divisions == (0, 1)


def test_build_grouping_segments_rejects_oversized_null_group(monkeypatch) -> None:
    with pytest.raises(
        ReadV3PlanningError,
        match=(
            r"above max_rows_per_partition=100 that cannot be split: "
            r"'__null__' with 150 rows \(NULL keys all hash into one bucket\)\. "
            r"Raise max_rows_per_partition"
        ),
    ):
        _build_with_groups(
            monkeypatch,
            [
                _prefix_group("Мо", 50),
                GroupingPartitionSegment(label="__null__", is_null=True, count=150),
            ],
            max_rows_per_partition=100,
        )


def test_build_grouping_segments_rejects_split_above_max_partitions(monkeypatch) -> None:
    # ceil(1000 / 80) = 13 sub-segments plus one regular group exceed max_partitions=10.
    with pytest.raises(
        ReadV3PlanningError,
        match=(
            r"'Мо' with 1000 rows \(splitting by key hash needs 14 segments, "
            r"above max_partitions=10\)"
        ),
    ):
        _build_with_groups(
            monkeypatch,
            [_prefix_group("Мо", 1000), _prefix_group("Хл", 40)],
            max_rows_per_partition=100,
            max_partitions=10,
        )


def test_build_grouping_segments_rejects_oversized_group_without_dialect_hash(
    monkeypatch,
) -> None:
    with pytest.raises(
        ReadV3PlanningError,
        match=r"'Мо' with 250 rows \(dialect 'nohash' has no hash expression to split it\)",
    ):
        _build_with_groups(
            monkeypatch,
            [_prefix_group("Мо", 250)],
            max_rows_per_partition=100,
            dialect=_NoHashDialect(),
        )


def _raw_key_group(values: list[str], count: int) -> GroupingPartitionSegment:
    return GroupingPartitionSegment(label="+".join(values), include_values=values, count=count)


def test_build_grouping_segments_rejects_oversized_single_key_value_group(monkeypatch) -> None:
    with pytest.raises(
        ReadV3PlanningError,
        match=r"'Молоко' with 250 rows \(a single key value cannot be spread by hashing\)",
    ):
        _build_with_groups(
            monkeypatch,
            [_raw_key_group(["Молоко"], 250)],
            max_rows_per_partition=100,
        )


def test_build_grouping_segments_splits_oversized_group_of_several_key_values(monkeypatch) -> None:
    result = _build_with_groups(
        monkeypatch,
        [_raw_key_group(["Молоко", "Хлеб"], 250)],
        max_rows_per_partition=100,
    )

    hash_sql = SqliteDialect().hash_expr(_NAME_SQL, 4)
    assert [segment.label for segment in result.segments] == [
        f"Молоко+Хлеб#{bucket}/4" for bucket in range(4)
    ]
    assert result.segments[0].predicate_sql == (
        f"({_NAME_SQL} IN ('Молоко', 'Хлеб')) AND {hash_sql} = 0"
    )
