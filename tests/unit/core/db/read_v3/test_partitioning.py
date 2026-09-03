from __future__ import annotations

import pytest

from core.db.read_v3.errors import ReadV3ConfigError, ReadV3PlanningError
from core.db.read_v3.models import PartitionStrategy, ReadSegment, SegmentDivision, ValueKind
from core.db.read_v3.partitioning.adapters import choose_partition_strategy
from core.db.read_v3.partitioning.divisions import build_divisions_from_segments, validate_divisions


def test_choose_partition_strategy_prefers_range_for_orderable_non_null() -> None:
    adapter = choose_partition_strategy(
        value_kind=ValueKind.NUMERIC,
        has_nulls=False,
        explicit_strategy=None,
    )
    assert adapter.strategy == PartitionStrategy.RANGE


def test_choose_partition_strategy_uses_hash_for_nullable() -> None:
    adapter = choose_partition_strategy(
        value_kind=ValueKind.STRING,
        has_nulls=True,
        explicit_strategy=None,
    )
    assert adapter.strategy == PartitionStrategy.HASH


def test_choose_partition_strategy_rejects_invalid_explicit_range() -> None:
    with pytest.raises(ReadV3ConfigError):
        choose_partition_strategy(
            value_kind=ValueKind.UNKNOWN,
            has_nulls=False,
            explicit_strategy="range",
        )


def test_validate_divisions_rejects_none() -> None:
    with pytest.raises(ReadV3PlanningError):
        validate_divisions((1, None, 3), expected_segments=2)


def test_build_divisions_from_segments_requires_contiguous_ranges() -> None:
    segments = [
        ReadSegment(
            label="s1",
            predicate_sql="1=1",
            order_by_sql="",
            division=SegmentDivision(start=1, end=2),
            strategy=PartitionStrategy.RANGE,
        ),
        ReadSegment(
            label="s2",
            predicate_sql="1=1",
            order_by_sql="",
            division=SegmentDivision(start=3, end=4),
            strategy=PartitionStrategy.RANGE,
        ),
    ]
    with pytest.raises(ReadV3PlanningError):
        build_divisions_from_segments(segments)
