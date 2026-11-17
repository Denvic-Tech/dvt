from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Sequence

import pandas as pd
from sqlalchemy.engine import Engine

from core.db.read_v3.dialects.base import SQLDialect
from core.db.read_v3.errors import ReadV3ConfigError, ReadV3PlanningError
from core.db.read_v3.grouping.builder import build_custom_segments
from core.db.read_v3.grouping.models import PartitionSegment as GroupingPartitionSegment
from core.db.read_v3.grouping.models import ValueKind as GroupingValueKind
from core.db.read_v3.grouping.spec import GroupingSpec, GroupingSpecError
from core.db.read_v3.models import PartitionStrategy, ReadSegment, SegmentDivision, ValueKind
from core.db.read_v3.sql_runner import read_sql_df


@dataclass(frozen=True)
class GroupingBuildResult:
    mode: str
    segments: list[ReadSegment]
    divisions: tuple[int, ...]


@dataclass(frozen=True)
class _GroupPlan:
    """One grouping segment before index assignment; ``expected_rows`` is an exact count."""

    label: str
    predicate_sql: str
    expected_rows: int | None
    is_null: bool = False
    is_single_value: bool = False


# Oversized groups at most this many per reason are listed in a planning error.
_MAX_REPORTED_GROUPS = 5


def _wrap_cte(cte_prefix_sql: Optional[str], sql: str) -> str:
    if cte_prefix_sql:
        return f"{cte_prefix_sql} {sql}"
    return sql


def _map_value_kind(value_kind: ValueKind) -> GroupingValueKind:
    mapping = {
        ValueKind.STRING: GroupingValueKind.STRING,
        ValueKind.UUID: GroupingValueKind.STRING,
        ValueKind.NUMERIC: GroupingValueKind.NUMERIC,
        ValueKind.DATE: GroupingValueKind.DATE,
        ValueKind.DATETIME: GroupingValueKind.DATETIME,
        ValueKind.BOOL: GroupingValueKind.BOOL,
    }
    mapped = mapping.get(value_kind)
    if mapped is None:
        raise ReadV3ConfigError(
            f"partition_grouping is not supported for value_kind={value_kind.value!r}"
        )
    return mapped


class V3GroupingHelper:
    def __init__(
        self,
        *,
        engine: Engine,
        dialect: SQLDialect,
        relation_sql: str,
        cte_prefix_sql: Optional[str],
        value_kind: GroupingValueKind,
    ) -> None:
        self.engine = engine
        self.dialect = dialect
        self.relation_sql = relation_sql
        self.cte_prefix_sql = cte_prefix_sql
        self.value_kind = value_kind

    def _query_df(self, sql: str) -> pd.DataFrame:
        return read_sql_df(self.engine, _wrap_cte(self.cte_prefix_sql, sql))

    def value_counts_expr(
        self,
        expr_sql: str,
        max_groups: Optional[int],
    ) -> list[tuple[Optional[object], int]]:
        limit_clause = f" {self.dialect.limit_offset(max_groups, 0)}" if max_groups else ""
        statement = (
            f"SELECT v, count(*) AS cnt "
            f"FROM (SELECT {expr_sql} AS v {self.relation_sql}) __dvt_group_values "
            f"WHERE v IS NOT NULL "
            f"GROUP BY v ORDER BY cnt DESC{limit_clause}"
        )
        values_df = self._query_df(statement)
        null_df = self._query_df(
            f"SELECT count(*) AS cnt {self.relation_sql} WHERE {expr_sql} IS NULL"
        )

        result: list[tuple[Optional[object], int]] = [(row.v, int(row.cnt)) for _, row in values_df.iterrows()]
        null_count = int(null_df.iloc[0, 0]) if not null_df.empty else 0
        if null_count:
            result.append((None, null_count))
        return result

    def null_count_expr(self, expr_sql: str) -> int:
        df = self._query_df(f"SELECT count(*) AS cnt {self.relation_sql} WHERE {expr_sql} IS NULL")
        if df.empty:
            return 0
        return int(df.iloc[0, 0])

    def min_max_expr(self, expr_sql: str) -> tuple[Optional[object], Optional[object]]:
        df = self._query_df(
            f"SELECT min({expr_sql}) AS min_v, max({expr_sql}) AS max_v "
            f"{self.relation_sql} WHERE {expr_sql} IS NOT NULL"
        )
        if df.empty:
            return None, None
        min_value = self._normalize_temporal_value(df.iloc[0, 0])
        max_value = self._normalize_temporal_value(df.iloc[0, 1])
        return min_value, max_value

    def count_predicate(self, predicate_sql: str) -> int:
        df = self._query_df(f"SELECT count(*) AS cnt {self.relation_sql} WHERE {predicate_sql}")
        if df.empty:
            return 0
        return int(df.iloc[0, 0])

    def count_range_expr(self, expr_sql: str, start: object, end: object, include_end: bool) -> int:
        op = "<=" if include_end else "<"
        predicate = (
            f"{expr_sql} >= {self.dialect.render_literal(start)} "
            f"AND {expr_sql} {op} {self.dialect.render_literal(end)}"
        )
        return self.count_predicate(predicate)

    def render_literal(self, value: object) -> str:
        return self.dialect.render_literal(value)

    def render_in_list(self, values: Sequence[object]) -> str:
        return self.dialect.render_in_list(values)

    def string_prefix_expr(self, col_expr: str, length: int, lower: bool) -> str:
        return self.dialect.string_prefix_expr(col_expr, length, lower)

    def hash_filter(self, col_name: str, buckets: int, bucket_list: Sequence[int]) -> str:
        if not bucket_list:
            return "1 = 0"
        col_sql = self.dialect.quote_ident(col_name)
        hash_sql = self.dialect.hash_expr(col_sql, buckets)
        if len(bucket_list) == 1:
            return f"{hash_sql} = {int(bucket_list[0])}"
        buckets_sql = ", ".join(str(int(bucket)) for bucket in bucket_list)
        return f"{hash_sql} IN ({buckets_sql})"

    def quantile_values(self, expr_sql: str, percentiles: Sequence[float]) -> list[Optional[object]]:
        if not percentiles:
            return []

        try:
            quantile_exprs = [
                f"{self.dialect.quantile_expr(expr_sql, percentile)} AS q{idx}"
                for idx, percentile in enumerate(percentiles)
            ]
            statement = f"SELECT {', '.join(quantile_exprs)} {self.relation_sql} WHERE {expr_sql} IS NOT NULL"
            df = self._query_df(statement)
            if df.empty:
                return [None for _ in percentiles]
            return [df.iloc[0, idx] for idx in range(len(percentiles))]
        except NotImplementedError:
            values_df = self._query_df(
                f"SELECT {expr_sql} AS v {self.relation_sql} WHERE {expr_sql} IS NOT NULL"
            )
            if values_df.empty:
                return [None for _ in percentiles]
            series = values_df["v"].dropna()
            if series.empty:
                return [None for _ in percentiles]
            return [series.quantile(percentile) for percentile in percentiles]

    def _normalize_temporal_value(self, value: object) -> object:
        if value is None:
            return None
        if self.value_kind == GroupingValueKind.DATETIME:
            if isinstance(value, datetime):
                return value
            parsed = pd.to_datetime(value, errors="coerce")
            if pd.isna(parsed):
                return value
            return parsed.to_pydatetime() if hasattr(parsed, "to_pydatetime") else parsed
        if self.value_kind == GroupingValueKind.DATE:
            if isinstance(value, date) and not isinstance(value, datetime):
                return value
            parsed = pd.to_datetime(value, errors="coerce")
            if pd.isna(parsed):
                return value
            if hasattr(parsed, "date"):
                return parsed.date()
            return value
        return value


def _render_segment_predicate(
    *,
    segment: GroupingPartitionSegment,
    key_sql: str,
    dialect: SQLDialect,
) -> str:
    expr = segment.value_expr or key_sql

    if segment.is_null:
        return f"{expr} IS NULL"

    if segment.include_values:
        return f"{expr} IN ({dialect.render_in_list(list(segment.include_values))})"

    if segment.exclude_values is not None:
        if segment.exclude_values:
            return (
                f"{expr} NOT IN ({dialect.render_in_list(list(segment.exclude_values))}) "
                f"AND {expr} IS NOT NULL"
            )
        return f"{expr} IS NOT NULL"

    if segment.hash_mod:
        buckets = list(segment.buckets or [])
        if not buckets:
            return "1 = 0"
        hash_sql = dialect.hash_expr(key_sql, segment.hash_mod)
        if len(buckets) == 1:
            return f"{hash_sql} = {int(buckets[0])}"
        buckets_sql = ", ".join(str(int(bucket)) for bucket in buckets)
        return f"{hash_sql} IN ({buckets_sql})"

    if segment.range_start is not None and segment.range_end is not None:
        op = "<=" if segment.include_end else "<"
        return (
            f"{expr} >= {dialect.render_literal(segment.range_start)} "
            f"AND {expr} {op} {dialect.render_literal(segment.range_end)}"
        )

    return "1 = 1"


def _split_bucket_count(rows: int, max_rows_per_partition: int) -> int:
    # Sub-segments target 80% of the ceiling so hash non-uniformity stays below it.
    target_rows = max(1, max_rows_per_partition * 4 // 5)
    return -(-rows // target_rows)


def _oversized_groups_error(
    *,
    mode: str,
    problems: list[tuple[_GroupPlan, str]],
    max_rows_per_partition: int,
) -> ReadV3PlanningError:
    groups_by_reason: dict[str, list[_GroupPlan]] = {}
    for group, reason in problems:
        groups_by_reason.setdefault(reason, []).append(group)

    details: list[str] = []
    for reason, groups in groups_by_reason.items():
        listed = ", ".join(
            f"{group.label!r} with {group.expected_rows} rows"
            for group in groups[:_MAX_REPORTED_GROUPS]
        )
        if len(groups) > _MAX_REPORTED_GROUPS:
            listed += f" and {len(groups) - _MAX_REPORTED_GROUPS} more"
        details.append(f"{listed} ({reason})")

    return ReadV3PlanningError(
        f"partition_grouping mode={mode!r} produced segments above "
        f"max_rows_per_partition={max_rows_per_partition} that cannot be split: "
        f"{'; '.join(details)}. Raise max_rows_per_partition, use a finer partition_grouping "
        "or another partition_col."
    )


def _split_oversized_groups(
    groups: list[_GroupPlan],
    *,
    mode: str,
    dialect: SQLDialect,
    key_sql: str,
    max_rows_per_partition: int,
    max_partitions: int,
) -> list[_GroupPlan]:
    """Replace each group above the ceiling by key-hash sub-groups, or fail planning."""
    problems: list[tuple[int, _GroupPlan, str]] = []
    splits: dict[int, tuple[int, str]] = {}
    for position, group in enumerate(groups):
        rows = group.expected_rows
        if rows is None or rows <= max_rows_per_partition:
            continue
        if group.is_null:
            problems.append((position, group, "NULL keys all hash into one bucket"))
            continue
        if group.is_single_value:
            problems.append((position, group, "a single key value cannot be spread by hashing"))
            continue
        buckets = _split_bucket_count(rows, max_rows_per_partition)
        try:
            hash_sql = dialect.hash_expr(key_sql, buckets)
        except NotImplementedError:
            problems.append(
                (position, group, f"dialect {dialect.name!r} has no hash expression to split it")
            )
            continue
        splits[position] = (buckets, hash_sql)

    segment_count = len(groups) + sum(buckets - 1 for buckets, _ in splits.values())
    if splits and segment_count > max_partitions:
        reason = (
            f"splitting by key hash needs {segment_count} segments, "
            f"above max_partitions={max_partitions}"
        )
        problems.extend((position, groups[position], reason) for position in splits)
    if problems:
        problems.sort(key=lambda problem: problem[0])
        raise _oversized_groups_error(
            mode=mode,
            problems=[(group, reason) for _, group, reason in problems],
            max_rows_per_partition=max_rows_per_partition,
        )

    expanded: list[_GroupPlan] = []
    for position, group in enumerate(groups):
        split = splits.get(position)
        if split is None:
            expanded.append(group)
            continue
        buckets, hash_sql = split
        sub_rows = -(-int(group.expected_rows or 0) // buckets)
        expanded.extend(
            _GroupPlan(
                label=f"{group.label}#{bucket}/{buckets}",
                predicate_sql=f"({group.predicate_sql}) AND {hash_sql} = {bucket}",
                expected_rows=sub_rows,
            )
            for bucket in range(buckets)
        )
    return expanded


def build_grouping_segments(
    *,
    engine: Engine,
    dialect: SQLDialect,
    relation_sql: str,
    cte_prefix_sql: Optional[str],
    key_sql: str,
    partition_key_name: str,
    value_kind: ValueKind,
    partition_grouping: object,
    total_rows: int,
    npartitions: int,
    limit: Optional[int],
    partition_granularity: Optional[str],
    max_rows_per_partition: int,
    max_partitions: int,
) -> GroupingBuildResult:
    try:
        grouping_spec = GroupingSpec.parse(partition_grouping)
    except GroupingSpecError as exc:
        raise ReadV3ConfigError(str(exc)) from exc

    if grouping_spec is None:
        raise ReadV3ConfigError("partition_grouping must not be null when grouping mode is enabled")

    legacy_value_kind = _map_value_kind(value_kind)
    helper = V3GroupingHelper(
        engine=engine,
        dialect=dialect,
        relation_sql=relation_sql,
        cte_prefix_sql=cte_prefix_sql,
        value_kind=legacy_value_kind,
    )

    try:
        legacy_segments = build_custom_segments(
            helper=helper,
            column_expr=key_sql,
            column_name=partition_key_name,
            value_kind=legacy_value_kind,
            spec=grouping_spec,
            total_rows=total_rows,
            npartitions=npartitions,
            limit=limit,
            partition_granularity=partition_granularity,
        )
    except GroupingSpecError as exc:
        raise ReadV3ConfigError(str(exc)) from exc

    if not legacy_segments:
        if total_rows == 0:
            empty_segment = ReadSegment(
                label="empty",
                predicate_sql="1=0",
                order_by_sql=f"ORDER BY {key_sql} ASC",
                division=SegmentDivision(start=0, end=1, include_end=True),
                strategy=PartitionStrategy.HASH,
                expected_rows=0,
                bucket_start=0,
                bucket_end=1,
                index_literal=0,
            )
            return GroupingBuildResult(
                mode=grouping_spec.mode,
                segments=[empty_segment],
                divisions=(0, 1),
            )
        raise ReadV3PlanningError(
            f"partition_grouping mode={grouping_spec.mode!r} produced no segments"
        )

    groups = [
        _GroupPlan(
            label=legacy_segment.label or f"group_{idx}",
            predicate_sql=_render_segment_predicate(
                segment=legacy_segment,
                key_sql=key_sql,
                dialect=dialect,
            ),
            expected_rows=legacy_segment.count,
            is_null=legacy_segment.is_null,
            # A group on the raw key with one included value holds a single key value.
            is_single_value=(
                legacy_segment.value_expr is None
                and legacy_segment.include_values is not None
                and len(legacy_segment.include_values) == 1
            ),
        )
        for idx, legacy_segment in enumerate(legacy_segments)
    ]
    groups = _split_oversized_groups(
        groups,
        mode=grouping_spec.mode,
        dialect=dialect,
        key_sql=key_sql,
        max_rows_per_partition=max_rows_per_partition,
        max_partitions=max_partitions,
    )

    segments: list[ReadSegment] = []
    for idx, group in enumerate(groups):
        segments.append(
            ReadSegment(
                label=group.label,
                predicate_sql=group.predicate_sql,
                order_by_sql=f"ORDER BY {key_sql} ASC",
                division=SegmentDivision(start=idx, end=idx + 1, include_end=True),
                strategy=PartitionStrategy.HASH,
                expected_rows=group.expected_rows,
                bucket_start=idx,
                bucket_end=idx + 1,
                index_literal=idx,
            )
        )

    divisions = tuple(range(0, len(segments) + 1))
    return GroupingBuildResult(mode=grouping_spec.mode, segments=segments, divisions=divisions)
