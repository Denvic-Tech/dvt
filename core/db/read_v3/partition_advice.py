"""Partition-key recommendations for read_v3 readers from collected key statistics (no I/O).

The rules mirror what the strict planners do with a key:

- sizing: the planner's automatic estimate (rows x estimated row width against the instance
  memory target) gives ``target_npartitions``; the segment ceiling is the planner default
  ``max(100_000, 4 x rows per partition)`` unless the caller fixes one;
- range boundaries and hash buckets never divide rows of one key value, and NULL keys form one
  hash bucket, so a key whose heaviest value or NULL group exceeds the ceiling is excluded, and so
  is a key with fewer distinct values than target partitions (segments would be fewer and larger);
- explicit range rejects NULL keys. Range boundaries cost one sort of the key per plan
  (``SQLDialect.range_boundaries_query`` on ClickHouse, PostgreSQL, MSSQL, MySQL and Oracle); one
  ``ORDER BY key ... OFFSET`` query per partition runs only on dialects without that statement or
  when it fails. The strategy follows the reading cost instead: a range segment on a key the
  relation is sorted or indexed by reads only its slice, while on any other key range and hash
  segments both scan the whole relation and hash keeps segments even when key values repeat.
  Sorted or indexed keys without NULLs get range, every other key hash with
  ``buckets = target_npartitions``; strings and UUIDs always hash;
- integer, date and datetime keys with low skew rank first, then other orderable keys, then
  strings; within a tier range before hash, keys without NULLs first, then lower skew. Skew is
  ``max_repeat / (non-NULL rows / distinct)``: 1 for a unique key.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from core.db.read_v3._auto_partition import finalize_partition_estimate
from core.db.read_v3.grouping.temporal import advance_granularity, floor_to_granularity
from core.db.read_v3.key_stats import KEY_VALUE_KINDS, ColumnKeyStats, RelationKeyStats
from core.db.read_v3.models import PartitionStrategy, ReadMode, ValueKind
from core.db.read_v3.planner.boundaries import (
    clamp_npartitions,
    default_max_rows_per_partition,
    infer_npartitions,
)
from core.db.read_v3.planner.key_skew import show_key_value

# A key whose heaviest value holds at most this many times the average rows per value ranks in
# the first tier (integers, dates, datetimes).
LOW_SKEW = 4.0
# An estimated heaviest value this close to the ceiling gets a warning instead of a clean pass.
ESTIMATE_WARNING_SHARE = 0.8
# Coarse to fine; DATE keys skip hour.
_GRANULARITIES = ("year", "month", "week", "day", "hour")
# Dialect names whose ``range_boundaries_query`` reads every range boundary in one statement.
SINGLE_QUERY_BOUNDARY_DIALECTS = frozenset({"clickhouse", "postgresql", "mssql", "mysql", "oracle"})
_WHOLE_RELATION_SCANS = (
    "range and hash segments would each scan the whole relation, and hash keeps segments even "
    "when key values repeat"
)


@dataclass(frozen=True)
class PartitionSizing:
    total_rows: int
    total_rows_estimated: bool
    bytes_per_row_est: int
    target_npartitions: int
    npartitions_source: str  # "planner_estimate" | "request"
    target_rows_per_partition: int
    # Ceiling every candidate is checked against.
    max_rows_per_partition: int
    max_rows_per_partition_source: str  # "planner_default" | "request"
    max_partitions: int


@dataclass(frozen=True)
class GranularityOption:
    partition_grouping: dict[str, Any]
    periods_est: int
    rows_per_period_est: int
    note: str


@dataclass(frozen=True)
class PartitionRecommendation:
    rank: int
    partition_col: str
    strategy: PartitionStrategy
    partition_grouping: dict[str, Any]
    npartitions: int
    max_rows_per_partition: int
    value_kind: ValueKind
    skew: float | None
    estimated: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    granularity_option: GranularityOption | None = None


@dataclass(frozen=True)
class ExcludedColumn:
    name: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class PartitionAdvice:
    sizing: PartitionSizing
    recommendations: tuple[PartitionRecommendation, ...]
    excluded: tuple[ExcludedColumn, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _Candidate:
    column: ColumnKeyStats
    tier: int
    skew: float
    strategy: PartitionStrategy


def _is_integer_key(column: ColumnKeyStats) -> bool:
    if column.value_kind != ValueKind.NUMERIC:
        return False
    if "int" in column.type_repr.lower():
        return True
    return isinstance(column.min_value, int) and isinstance(column.max_value, int)


def _rows(value: int | None) -> int:
    return max(0, value or 0)


def _skew_of(column: ColumnKeyStats, total_rows: int) -> float:
    non_null = max(0, total_rows - _rows(column.null_count))
    distinct = column.distinct_count or 0
    if non_null <= 0 or distinct <= 0 or not column.max_repeat:
        return 1.0
    return column.max_repeat / (non_null / distinct)


def build_sizing(
    stats: RelationKeyStats,
    *,
    min_rows_per_partition: int,
    target_partition_mem_mb: int,
    partitioning_overhead_coef: float,
    max_partitions: int,
    npartitions: int | None = None,
    max_rows_per_partition: int | None = None,
) -> PartitionSizing:
    """Target partition count and segment ceiling as the planner computes them."""
    if npartitions is None:
        estimate = finalize_partition_estimate(
            dialect_name=stats.dialect.lower(),
            bytes_per_row_est=stats.bytes_per_row_est,
            effective_rows_est=stats.total_rows,
            min_rows_per_part=min_rows_per_partition,
            target_partition_mem_mb=target_partition_mem_mb,
            partitioning_overhead_coef=partitioning_overhead_coef,
            max_partitions=max_partitions,
        )
        target_npartitions, npartitions_source = estimate.npartitions, "planner_estimate"
    else:
        target_npartitions = infer_npartitions(stats.total_rows, npartitions)
        npartitions_source = "request"
    target_npartitions = clamp_npartitions(target_npartitions, stats.total_rows)
    target_rows = max(1, math.ceil(max(stats.total_rows, 1) / target_npartitions))
    if max_rows_per_partition is not None:
        ceiling, source = max_rows_per_partition, "request"
    else:
        ceiling = default_max_rows_per_partition(stats.total_rows, target_npartitions)
        source = "planner_default"
    return PartitionSizing(
        total_rows=stats.total_rows,
        total_rows_estimated=stats.total_rows_estimated,
        bytes_per_row_est=stats.bytes_per_row_est,
        target_npartitions=target_npartitions,
        npartitions_source=npartitions_source,
        target_rows_per_partition=target_rows,
        max_rows_per_partition=ceiling,
        max_rows_per_partition_source=source,
        max_partitions=max_partitions,
    )


def _exclusion_reasons(column: ColumnKeyStats, sizing: PartitionSizing) -> list[str]:
    if not column.available:
        return [column.note or "statistics are not available"]
    if column.value_kind not in KEY_VALUE_KINDS:
        return [f"type {column.type_repr!r} ({column.value_kind.value}) is not a usable key"]
    reasons: list[str] = []
    ceiling = sizing.max_rows_per_partition
    max_repeat = _rows(column.max_repeat)
    null_count = _rows(column.null_count)
    if max_repeat > ceiling:
        reasons.append(
            f"value {show_key_value(column.max_repeat_value)} occurs {max_repeat} times, above "
            f"max_rows_per_partition={ceiling}: one range or hash segment cannot hold it; "
            f"{_ceiling_needed(max_repeat, sizing)}"
        )
    if null_count > ceiling:
        reasons.append(
            f"{null_count} NULL keys form one hash bucket above max_rows_per_partition={ceiling}; "
            f"{_ceiling_needed(null_count, sizing)}"
        )
    distinct = column.distinct_count or 0
    if distinct < sizing.target_npartitions:
        reasons.append(
            f"{distinct} distinct values for target_npartitions={sizing.target_npartitions}: "
            "segments would be fewer and larger than planned"
            + (
                f"; it fits npartitions <= {distinct} (about "
                f"{math.ceil(sizing.total_rows / distinct)} rows per partition)"
                if distinct
                else ""
            )
        )
    return reasons


def _ceiling_needed(group_rows: int, sizing: PartitionSizing) -> str:
    rows = group_rows + sizing.target_rows_per_partition
    megabytes = math.ceil(rows * sizing.bytes_per_row_est / 1024**2)
    return (
        f"it needs max_rows_per_partition >= {rows}, about {megabytes} MB for that segment "
        "at the estimated row width"
    )


def _tier(column: ColumnKeyStats, skew: float) -> int:
    if column.value_kind in {ValueKind.STRING, ValueKind.UUID}:
        return 2
    if skew <= LOW_SKEW and (
        _is_integer_key(column) or column.value_kind in {ValueKind.DATE, ValueKind.DATETIME}
    ):
        return 0
    return 1


def _strategy(column: ColumnKeyStats, mode: ReadMode) -> PartitionStrategy:
    if (
        mode == ReadMode.TABLE
        and column.indexed
        and not column.null_count
        and column.value_kind not in {ValueKind.STRING, ValueKind.UUID}
    ):
        return PartitionStrategy.RANGE
    return PartitionStrategy.HASH


def _count_periods(start: date, end: date, granularity: str, limit: int) -> int | None:
    cursor = floor_to_granularity(start, granularity)
    periods = 1
    while cursor < end:
        cursor = advance_granularity(cursor, granularity)
        periods += 1
        if periods > limit:
            return None
    return periods


def _range_boundaries_cost(dialect: str) -> str:
    if dialect.lower() in SINGLE_QUERY_BOUNDARY_DIALECTS:
        return "one sort of the key per plan"
    return f"one ORDER BY key ... OFFSET query per partition on {dialect}"


def _granularity_option(
    column: ColumnKeyStats, sizing: PartitionSizing
) -> GranularityOption | None:
    """Coarsest period whose uniform row estimate fits the ceiling within the partition limit."""
    low, high = column.min_value, column.max_value
    if column.value_kind == ValueKind.DATETIME:
        valid = isinstance(low, datetime) and isinstance(high, datetime)
        granularities = _GRANULARITIES
    else:
        # A DATE key holds one value per day: hour periods would only repeat days.
        valid = column.value_kind == ValueKind.DATE and type(low) is date and type(high) is date
        granularities = _GRANULARITIES[:-1]
    if not valid:
        return None
    non_null = max(1, sizing.total_rows - _rows(column.null_count))
    for granularity in granularities:
        periods = _count_periods(low, high, granularity, sizing.max_partitions)
        if periods is None:
            return None
        rows_per_period = math.ceil(non_null / periods)
        if rows_per_period <= sizing.max_rows_per_partition:
            return GranularityOption(
                partition_grouping={"mode": "granularity", "granularity": granularity},
                periods_est=periods,
                rows_per_period_est=rows_per_period,
                note=(
                    f"estimate assuming rows spread evenly between {low} and {high}; planning "
                    f"runs one COUNT query per period. Count rows of the largest {granularity} "
                    "before choosing it: periods above max_rows_per_partition are split by key "
                    "hash, which cannot divide one repeated value"
                ),
            )
    return None


def _recommendation(
    rank: int,
    candidate: _Candidate,
    sizing: PartitionSizing,
    stats: RelationKeyStats,
) -> PartitionRecommendation:
    column = candidate.column
    strategy = candidate.strategy
    max_repeat = _rows(column.max_repeat)
    null_count = _rows(column.null_count)
    target_rows = sizing.target_rows_per_partition
    ceiling = sizing.max_rows_per_partition

    heaviest_group = max(max_repeat, null_count if strategy == PartitionStrategy.HASH else 0)
    expected_largest = target_rows + heaviest_group
    if sizing.max_rows_per_partition_source == "request":
        recommended_ceiling = ceiling
    else:
        recommended_ceiling = max(ceiling, 2 * expected_largest)

    reasons = [
        f"{column.value_kind.value} key ({column.type_repr}), "
        f"{column.distinct_count} distinct values for {sizing.target_npartitions} partitions",
        f"heaviest value {show_key_value(column.max_repeat_value)}: {max_repeat} rows, "
        f"skew {candidate.skew:.2f}",
    ]
    warnings: list[str] = []
    boundaries_cost = _range_boundaries_cost(stats.dialect)
    if strategy == PartitionStrategy.RANGE:
        reasons.append(
            f"relation is sorted or indexed by {column.name!r} and the key has no NULLs: each "
            f"range segment reads only its slice of the key; boundaries take {boundaries_cost}"
        )
    else:
        why = []
        if column.value_kind in {ValueKind.STRING, ValueKind.UUID}:
            why.append("string keys are read with hash buckets")
        elif null_count:
            why.append(f"{null_count} NULL keys rule out range")
        elif stats.mode == ReadMode.QUERY:
            why.append(f"a query result has no index: {_WHOLE_RELATION_SCANS}")
        else:
            why.append(
                f"relation is not sorted or indexed by {column.name!r}: {_WHOLE_RELATION_SCANS} "
                f"(range boundaries would take {boundaries_cost})"
            )
        reasons.append(f"hash with buckets={sizing.target_npartitions}: {'; '.join(why)}")
        warnings.append(
            f"every hash segment filters the whole relation: {sizing.target_npartitions} scans "
            "of the read columns"
            + (
                " (columnar, so only those columns are read)"
                if stats.dialect == "clickhouse"
                else ""
            )
        )
        if null_count:
            warnings.append(f"the {null_count} NULL keys all land in one hash bucket")
    if expected_largest > ceiling:
        warnings.append(
            f"the segment holding the heaviest value can reach about {expected_largest} rows, "
            f"above max_rows_per_partition={ceiling}"
            + (
                f"; the recommendation raises it to {recommended_ceiling}"
                if recommended_ceiling > ceiling
                else "; reading that segment can fail"
            )
        )
    if column.estimated:
        warnings.append(
            f"statistics are estimates (source={column.source.value if column.source else None})"
        )
        if max_repeat > ESTIMATE_WARNING_SHARE * ceiling:
            warnings.append(
                "the estimated heaviest value is close to the ceiling; "
                "verify it with an exact count"
            )

    partition_grouping: dict[str, Any] = {"mode": strategy.value}
    if strategy == PartitionStrategy.HASH:
        partition_grouping["buckets"] = sizing.target_npartitions
    return PartitionRecommendation(
        rank=rank,
        partition_col=column.name,
        strategy=strategy,
        partition_grouping=partition_grouping,
        npartitions=sizing.target_npartitions,
        max_rows_per_partition=recommended_ceiling,
        value_kind=column.value_kind,
        skew=round(candidate.skew, 3),
        estimated=column.estimated,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
        granularity_option=_granularity_option(column, sizing),
    )


def advise_partitioning(
    stats: RelationKeyStats,
    *,
    min_rows_per_partition: int,
    target_partition_mem_mb: int,
    partitioning_overhead_coef: float,
    max_partitions: int,
    npartitions: int | None = None,
    max_rows_per_partition: int | None = None,
) -> PartitionAdvice:
    """Rank candidate keys of ``stats`` and explain every excluded one.

    ``npartitions`` and ``max_rows_per_partition`` are the reader inputs of the same names;
    omitted, they take the planner's automatic values.
    """
    sizing = build_sizing(
        stats,
        min_rows_per_partition=min_rows_per_partition,
        target_partition_mem_mb=target_partition_mem_mb,
        partitioning_overhead_coef=partitioning_overhead_coef,
        max_partitions=max_partitions,
        npartitions=npartitions,
        max_rows_per_partition=max_rows_per_partition,
    )
    candidates: list[_Candidate] = []
    excluded: list[ExcludedColumn] = []
    for column in stats.columns:
        reasons = _exclusion_reasons(column, sizing)
        if reasons:
            excluded.append(ExcludedColumn(name=column.name, reasons=tuple(reasons)))
            continue
        skew = _skew_of(column, stats.total_rows)
        candidates.append(
            _Candidate(
                column=column,
                tier=_tier(column, skew),
                skew=skew,
                strategy=_strategy(column, stats.mode),
            )
        )
    candidates.sort(
        key=lambda item: (
            item.tier,
            item.strategy != PartitionStrategy.RANGE,
            # NULL keys add their whole group to one hash bucket.
            _rows(item.column.null_count) > 0,
            item.skew,
            _rows(item.column.max_repeat),
            -(item.column.distinct_count or 0),
        )
    )
    warnings: list[str] = []
    if stats.total_rows_estimated:
        warnings.append("total_rows is a catalog estimate")
    if stats.sample_method:
        warnings.append(
            f"statistics above {stats.sample_threshold_rows} rows are estimated "
            f"({stats.sample_method}); verify a close call with an exact count"
        )
    if not candidates:
        warnings.append(
            "no profiled column fits this sizing: see the excluded columns for the "
            "max_rows_per_partition or npartitions each would need, profile other columns, "
            "or prepare a better key in the source"
        )
    return PartitionAdvice(
        sizing=sizing,
        recommendations=tuple(
            _recommendation(rank, candidate, sizing, stats)
            for rank, candidate in enumerate(candidates, start=1)
        ),
        excluded=tuple(excluded),
        warnings=tuple(warnings),
    )
