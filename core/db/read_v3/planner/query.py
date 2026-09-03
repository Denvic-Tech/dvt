from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal
from numbers import Number

import pandas as pd
from sqlalchemy.engine import Engine

from core.db.read_v3._auto_partition import estimate_query_partitions
from core.db.read_v3.datetime_precision import (
    ReadV3DateTimePrecision,
    normalize_datetime_precision,
)
from core.db.read_v3.dialects import resolve_dialect
from core.db.read_v3.embedded_query import build_read_v3_query_embedding
from core.db.read_v3.errors import ReadV3ConfigError, ReadV3PlanningError
from core.db.read_v3.grouping.spec import GroupingSpec, GroupingSpecError
from core.db.read_v3.models import (
    SUPPORTED_OUTPUT_VALUE_KINDS,
    PartitionStrategy,
    ReadMode,
    ReadV3Plan,
    ValueKind,
)
from core.db.read_v3.partitioning.adapters import choose_partition_strategy
from core.db.read_v3.partitioning.divisions import validate_divisions
from core.db.read_v3.partitioning.grouping import build_grouping_segments
from core.db.read_v3.planner.boundaries import (
    build_hash_segments,
    build_range_segments,
    infer_npartitions,
    query_row_stats,
)
from core.db.read_v3.query_metadata import describe_query_columns
from core.db.read_v3.sql_runner import read_sql_df


def _build_lookup(columns: Sequence[str]) -> dict[str, str]:
    return {column.lower(): column for column in columns}


def _resolve_column(name: str, lookup: dict[str, str]) -> str:
    key = name.lower()
    if key not in lookup:
        raise ReadV3PlanningError(
            f"Partition column {name!r} was not found in query result columns {list(lookup.values())!r}"
        )
    return lookup[key]


def _resolve_selected_columns(columns: Sequence[str] | None, lookup: dict[str, str]) -> list[str]:
    if columns is None:
        return list(lookup.values())
    resolved: list[str] = []
    for column in columns:
        resolved.append(_resolve_column(column, lookup))
    return resolved


def _map_columns_by_lookup(columns: Sequence[str], lookup: dict[str, str]) -> list[str]:
    return [_resolve_column(column, lookup) for column in columns]


def _resolve_public_query_columns(
    result_columns: Sequence[str],
    described_columns: Sequence[tuple[str, str]],
) -> list[str]:
    described_lookup = {
        str(column_name).lower(): str(column_name)
        for column_name, _type_repr in described_columns
        if str(column_name).strip()
    }
    public_columns: list[str] = []
    for result_column in result_columns:
        resolved = described_lookup.get(str(result_column).lower(), str(result_column))
        public_columns.append(resolved)
    return public_columns


def _infer_kind_from_value(value: object) -> ValueKind:  # noqa: PLR0911
    if value is None:
        return ValueKind.UNKNOWN
    if isinstance(value, (dict, list, tuple)):
        return ValueKind.JSON
    if pd.isna(value):
        return ValueKind.UNKNOWN
    if isinstance(value, bool):
        return ValueKind.BOOL
    if isinstance(value, (Number, Decimal)):
        return ValueKind.NUMERIC
    if isinstance(value, datetime):
        return ValueKind.DATETIME
    if isinstance(value, date):
        return ValueKind.DATE
    return ValueKind.STRING


def _apply_relation_limit(
    *,
    relation_sql: str,
    key_sql: str,
    limit: int | None,
    dialect,
) -> str:
    if limit is None:
        return relation_sql
    if limit <= 0:
        raise ReadV3ConfigError("limit must be positive")
    limited_select_sql = (
        f"SELECT * {relation_sql} ORDER BY {key_sql} ASC {dialect.limit_offset(limit, 0)}"
    )
    return f"FROM ({limited_select_sql}) __dvt_limited"


def _grouping_mode(raw: object | None) -> GroupingSpec | None:
    if raw is None:
        return None
    try:
        return GroupingSpec.parse(raw)
    except GroupingSpecError as exc:
        raise ReadV3ConfigError(str(exc)) from exc


def _grouping_npartitions_override(
    *,
    grouping: GroupingSpec | None,
    fallback: int,
) -> int:
    if grouping is None or grouping.mode != "hash":
        return fallback
    buckets = grouping.params.get("buckets") or grouping.params.get("mod")
    if buckets is None:
        return fallback
    if not isinstance(buckets, int) or buckets <= 0:
        raise ReadV3ConfigError("partition_grouping.hash requires positive integer buckets")
    return buckets


def _query_preview_for_error(query: str, *, max_len: int = 160) -> str:
    normalized = " ".join((query or "").split())
    if len(normalized) <= max_len:
        return normalized
    return f"{normalized[:max_len]}..."


def _validate_supported_output_column_kinds(
    *,
    selected_columns: Sequence[str],
    output_column_kinds: dict[str, ValueKind],
    output_column_type_repr: dict[str, str],
    query_preview: str,
) -> None:
    unsupported_columns = [
        column
        for column in selected_columns
        if output_column_kinds.get(column, ValueKind.UNKNOWN) not in SUPPORTED_OUTPUT_VALUE_KINDS
    ]
    if not unsupported_columns:
        return

    details = {
        column: {
            "kind": output_column_kinds.get(column, ValueKind.UNKNOWN).value,
            "type": output_column_type_repr.get(column, ""),
        }
        for column in unsupported_columns
    }
    raise ReadV3PlanningError(
        "Strict read_v3 could not infer output column kinds in query mode: "
        f"query={query_preview!r}, columns={details!r}. "
        "Add explicit casts in query so each output column has a deterministic type."
    )


def _validate_partition_key_kind(
    *,
    key_kind: ValueKind,
    query_preview: str,
    resolved_partition_col: str,
    partition_key_type_repr: str,
) -> None:
    if key_kind == ValueKind.JSON:
        raise ReadV3PlanningError(
            "Strict read_v3 does not support JSON partition keys in query mode: "
            f"query={query_preview!r}, column={resolved_partition_col!r}, "
            f"kind={key_kind.value!r}, type={partition_key_type_repr!r}. "
            "Choose a scalar partition column or add an explicit cast for partition_col in query."
        )


def _infer_non_null_sample_kinds_by_column(
    *,
    engine: Engine,
    cte_prefix_sql: str,
    relation_sql: str,
    columns: Sequence[str],
    sql_name_lookup: dict[str, str],
    dialect,
) -> dict[str, ValueKind]:
    inferred: dict[str, ValueKind] = {}
    for column in columns:
        source_name = sql_name_lookup.get(column.lower(), column)
        col_sql = dialect.quote_result_column(source_name)
        sample_sql = (
            f"{cte_prefix_sql} SELECT {col_sql} AS __dvt_sample "
            f"{relation_sql} WHERE {col_sql} IS NOT NULL "
            f"{dialect.limit_offset(1, 0)}"
        )
        try:
            sample_df = read_sql_df(engine, sample_sql)
        except Exception:
            inferred[column.lower()] = ValueKind.UNKNOWN
            continue

        if sample_df.empty:
            inferred[column.lower()] = ValueKind.UNKNOWN
            continue

        inferred[column.lower()] = _infer_kind_from_value(sample_df.iloc[0]["__dvt_sample"])
    return inferred


def _query_non_null_sample_value(
    *,
    engine: Engine,
    cte_prefix_sql: str,
    relation_sql: str,
    column: str,
    sql_name_lookup: dict[str, str],
    dialect,
) -> object | None:
    source_name = sql_name_lookup.get(column.lower(), column)
    col_sql = dialect.quote_result_column(source_name)
    sample_sql = (
        f"{cte_prefix_sql} SELECT {col_sql} AS __dvt_sample "
        f"{relation_sql} WHERE {col_sql} IS NOT NULL "
        f"{dialect.limit_offset(1, 0)}"
    )
    sample_df = read_sql_df(engine, sample_sql)
    if sample_df.empty:
        return None
    return sample_df.iloc[0]["__dvt_sample"]


class QueryReadPlanner:
    def build_plan(
        self,
        engine: Engine,
        query: str,
        *,
        min_rows_per_partition: int,
        target_partition_mem_mb: int,
        partitioning_overhead_coef: float,
        max_partitions: int,
        partition_col: str | None,
        columns: Sequence[str] | None = None,
        npartitions: int | None = None,
        limit: int | None = None,
        max_rows_per_partition: int | None = None,
        partition_grouping: dict | None = None,
        datetime_precision: ReadV3DateTimePrecision | str | None = None,
    ) -> ReadV3Plan:
        resolved_datetime_precision = normalize_datetime_precision(datetime_precision)
        grouping_spec = _grouping_mode(partition_grouping)
        if not partition_col:
            raise ReadV3ConfigError("partition_col is required in read_v3 query mode")

        dialect = resolve_dialect(engine)
        normalized_query = query.strip().rstrip(";")
        if not normalized_query:
            raise ReadV3ConfigError("query is empty")
        query_preview = _query_preview_for_error(normalized_query)
        try:
            query_embedding = build_read_v3_query_embedding(
                normalized_query,
                dialect_name=dialect.name,
            )
        except ValueError as exc:
            raise ReadV3ConfigError(str(exc)) from exc

        cte_prefix_sql = query_embedding.cte_prefix_sql
        relation_sql = query_embedding.relation_sql

        meta_sql = f"{cte_prefix_sql} SELECT * FROM user_query WHERE 1=0"
        meta_df = read_sql_df(engine, meta_sql)
        query_columns = [str(column) for column in meta_df.columns]
        described_columns = describe_query_columns(engine, normalized_query)
        if not query_columns and described_columns:
            query_columns = [str(column_name) for column_name, _ in described_columns]
        if not query_columns:
            raise ReadV3PlanningError("Query does not expose columns; cannot build read_v3 plan")

        public_columns = _resolve_public_query_columns(query_columns, described_columns)
        public_lookup = _build_lookup(public_columns)
        resolved_partition_col = _resolve_column(partition_col, public_lookup)
        selected_columns = _resolve_selected_columns(columns, public_lookup)
        detected_type_repr_by_lower = {
            column_name.lower(): type_repr for column_name, type_repr in described_columns
        }
        sql_name_lookup = (
            _build_lookup([column_name for column_name, _ in described_columns]) or public_lookup
        )
        selected_sql_columns = _map_columns_by_lookup(selected_columns, sql_name_lookup)
        partition_key_sql_name = _resolve_column(resolved_partition_col, sql_name_lookup)
        detected_kinds_by_lower = {
            column_name: dialect.detect_value_kind(type_repr)
            for column_name, type_repr in detected_type_repr_by_lower.items()
        }
        output_column_kinds = {
            column: detected_kinds_by_lower.get(column.lower(), ValueKind.UNKNOWN)
            for column in selected_columns
        }
        unknown_output_columns = [
            column for column, kind in output_column_kinds.items() if kind == ValueKind.UNKNOWN
        ]
        if unknown_output_columns:
            sampled_kinds_by_lower = _infer_non_null_sample_kinds_by_column(
                engine=engine,
                cte_prefix_sql=cte_prefix_sql,
                relation_sql=relation_sql,
                columns=unknown_output_columns,
                sql_name_lookup=sql_name_lookup,
                dialect=dialect,
            )
            for column in unknown_output_columns:
                sampled_kind = sampled_kinds_by_lower.get(column.lower(), ValueKind.UNKNOWN)
                if sampled_kind != ValueKind.UNKNOWN:
                    output_column_kinds[column] = sampled_kind

        output_column_type_repr = {
            column: detected_type_repr_by_lower.get(column.lower(), "")
            for column in selected_columns
        }
        _validate_supported_output_column_kinds(
            selected_columns=selected_columns,
            output_column_kinds=output_column_kinds,
            output_column_type_repr=output_column_type_repr,
            query_preview=query_preview,
        )
        partition_key_type_repr = detected_type_repr_by_lower.get(
            resolved_partition_col.lower(), ""
        )
        key_kind = detected_kinds_by_lower.get(resolved_partition_col.lower(), ValueKind.UNKNOWN)
        sample_value = None
        if key_kind == ValueKind.UNKNOWN:
            sample_value = _query_non_null_sample_value(
                engine=engine,
                cte_prefix_sql=cte_prefix_sql,
                relation_sql=relation_sql,
                column=resolved_partition_col,
                sql_name_lookup=sql_name_lookup,
                dialect=dialect,
            )
            key_kind = _infer_kind_from_value(sample_value)
        _validate_partition_key_kind(
            key_kind=key_kind,
            query_preview=query_preview,
            resolved_partition_col=resolved_partition_col,
            partition_key_type_repr=partition_key_type_repr,
        )

        key_sql = dialect.quote_result_column(partition_key_sql_name)
        relation_sql = _apply_relation_limit(
            relation_sql=relation_sql,
            key_sql=key_sql,
            limit=limit,
            dialect=dialect,
        )
        min_v, max_v, total_rows, non_null_rows = query_row_stats(
            engine=engine,
            dialect=dialect,
            cte_prefix_sql=cte_prefix_sql,
            relation_sql=relation_sql,
            key_sql=key_sql,
        )

        if sample_value is None:
            sample_sql = (
                f"{cte_prefix_sql} SELECT {key_sql} AS sample_value "
                f"{relation_sql} WHERE {key_sql} IS NOT NULL "
                f"ORDER BY {key_sql} ASC {dialect.limit_offset(1, 0)}"
            )
            sample_df = read_sql_df(engine, sample_sql)
            sample_value = None if sample_df.empty else sample_df.iloc[0]["sample_value"]

        if key_kind == ValueKind.UNKNOWN and sample_value is not None:
            key_kind = _infer_kind_from_value(sample_value)
        if key_kind == ValueKind.UNKNOWN and sample_value is None:
            key_kind = output_column_kinds.get(resolved_partition_col, ValueKind.UNKNOWN)
        if key_kind == ValueKind.UNKNOWN:
            raise ReadV3PlanningError(
                "Strict read_v3 could not infer partition key kind in query mode: "
                f"query={query_preview!r}, column={resolved_partition_col!r}, "
                f"kind={key_kind.value!r}, type={partition_key_type_repr!r}. "
                "Add explicit cast for partition_col in query."
            )

        has_nulls = non_null_rows < total_rows
        auto_partition_estimate = None
        if npartitions is None:
            auto_partition_estimate = estimate_query_partitions(
                engine=engine,
                dialect=dialect,
                cte_prefix_sql=cte_prefix_sql,
                relation_sql=relation_sql,
                selected_sql_columns=selected_sql_columns,
                effective_rows_est=total_rows,
                output_column_type_repr=output_column_type_repr,
                min_rows_per_part=min_rows_per_partition,
                target_partition_mem_mb=target_partition_mem_mb,
                partitioning_overhead_coef=partitioning_overhead_coef,
                max_partitions=max_partitions,
            )
            target_npartitions = auto_partition_estimate.npartitions
        else:
            target_npartitions = infer_npartitions(total_rows, npartitions)
        target_npartitions = _grouping_npartitions_override(
            grouping=grouping_spec,
            fallback=target_npartitions,
        )
        target_npartitions = 1 if total_rows <= 0 else min(target_npartitions, total_rows)

        output_column_select_exprs = {
            column: dialect.output_select_expr(
                dialect.quote_result_column(sql_name),
                output_name=column,
                type_repr=output_column_type_repr.get(column, ""),
            )
            for column, sql_name in zip(selected_columns, selected_sql_columns, strict=False)
        }
        select_exprs: list[str] = [output_column_select_exprs[column] for column in selected_columns]
        partition_key_alias = "__dvt_partition_key"
        hash_bucket_alias = "__dvt_partition_bucket"
        index_column_name = resolved_partition_col
        adapter_reason = "custom grouping"

        if grouping_spec is not None and grouping_spec.mode not in {"range", "hash"}:
            grouping_result = build_grouping_segments(
                engine=engine,
                dialect=dialect,
                relation_sql=relation_sql,
                cte_prefix_sql=cte_prefix_sql,
                key_sql=key_sql,
                partition_key_name=resolved_partition_col,
                value_kind=key_kind,
                partition_grouping=grouping_spec,
                total_rows=total_rows,
                npartitions=target_npartitions,
                limit=limit,
                partition_granularity=None,
            )
            segments = grouping_result.segments
            divisions = validate_divisions(
                grouping_result.divisions,
                expected_segments=len(grouping_result.segments),
            )
            strategy = PartitionStrategy.HASH
            hash_sql = None
            index_column_name = hash_bucket_alias
            adapter_reason = f"custom grouping mode={grouping_result.mode}"
        else:
            explicit_strategy = grouping_spec.mode if grouping_spec is not None else None
            adapter = choose_partition_strategy(
                value_kind=key_kind,
                has_nulls=has_nulls,
                explicit_strategy=explicit_strategy,
            )
            adapter_reason = adapter.reason
            if adapter.strategy == PartitionStrategy.RANGE:
                segments, divisions, _, _ = build_range_segments(
                    engine=engine,
                    dialect=dialect,
                    cte_prefix_sql=cte_prefix_sql,
                    relation_sql=relation_sql,
                    key_sql=key_sql,
                    npartitions=target_npartitions,
                )
                strategy = PartitionStrategy.RANGE
                hash_sql = None
            else:
                hash_sql = dialect.hash_expr(key_sql, target_npartitions)
                segments, divisions, _ = build_hash_segments(
                    key_sql=key_sql,
                    hash_sql=hash_sql,
                    npartitions=target_npartitions,
                    total_rows=total_rows,
                )
                strategy = PartitionStrategy.HASH
            divisions = validate_divisions(divisions, expected_segments=len(segments))

        if strategy == PartitionStrategy.RANGE and (
            resolved_partition_col not in selected_columns
            or dialect.requires_string_output_cast(partition_key_type_repr)
        ):
            select_exprs.append(f"{key_sql} AS {dialect.quote_ident(partition_key_alias)}")
            index_column_name = partition_key_alias

        if strategy == PartitionStrategy.HASH and hash_sql is not None:
            select_exprs.append(f"{hash_sql} AS {dialect.quote_ident(hash_bucket_alias)}")
            if resolved_partition_col not in selected_columns:
                select_exprs.append(f"{key_sql} AS {dialect.quote_ident(partition_key_alias)}")
            index_column_name = hash_bucket_alias

        if max_rows_per_partition is None:
            baseline = max(1, math.ceil(max(total_rows, 1) / max(target_npartitions, 1)))
            max_rows_per_partition = max(100_000, baseline * 4)

        if max_rows_per_partition <= 0:
            raise ReadV3ConfigError("max_rows_per_partition must be positive")

        return ReadV3Plan(
            mode=ReadMode.QUERY,
            dialect=dialect.name,
            cte_prefix_sql=cte_prefix_sql,
            relation_sql=relation_sql,
            select_exprs=select_exprs,
            output_columns=selected_columns,
            partition_key_name=resolved_partition_col,
            partition_key_kind=key_kind,
            strategy=strategy,
            segments=segments,
            divisions=divisions,
            max_rows_per_partition=max_rows_per_partition,
            partition_key_type_repr=partition_key_type_repr,
            partition_key_alias=partition_key_alias,
            hash_bucket_alias=hash_bucket_alias,
            index_column_name=index_column_name,
            total_rows=total_rows,
            npartitions=target_npartitions,
            output_column_kinds=output_column_kinds,
            output_column_type_repr=output_column_type_repr,
            output_column_sql_names=dict(zip(selected_columns, selected_sql_columns, strict=False)),
            output_column_select_exprs=output_column_select_exprs,
            partition_key_sql_name=partition_key_sql_name,
            extra_warnings=[
                f"strategy_reason={adapter_reason}",
                f"limit={limit!r}",
                f"sample_value={sample_value!r}",
                f"min={min_v!r}",
                f"max={max_v!r}",
                f"auto_npartitions={getattr(auto_partition_estimate, 'npartitions', None)!r}",
                f"auto_rows_per_part={getattr(auto_partition_estimate, 'rows_per_part', None)!r}",
                f"auto_bytes_per_row={getattr(auto_partition_estimate, 'bytes_per_row_est', None)!r}",
            ],
            datetime_precision=resolved_datetime_precision,
        )
