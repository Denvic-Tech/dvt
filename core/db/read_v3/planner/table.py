from __future__ import annotations

import math
from collections.abc import Sequence

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from core.db.read_v3._auto_partition import estimate_table_partitions
from core.db.read_v3.datetime_precision import (
    ReadV3DateTimePrecision,
    normalize_datetime_precision,
)
from core.db.read_v3.dialects import resolve_dialect
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
from core.db.read_v3.query_metadata import describe_mssql_table_column_types


def _build_lookup(columns: Sequence[str]) -> dict[str, str]:
    return {column.lower(): column for column in columns}


def _resolve_column(name: str, lookup: dict[str, str]) -> str:
    key = name.lower()
    if key not in lookup:
        raise ReadV3PlanningError(
            f"Column {name!r} was not found in table columns {list(lookup.values())!r}"
        )
    return lookup[key]


def _ensure_columns_exist(columns: Sequence[str], lookup: dict[str, str]) -> list[str]:
    return [_resolve_column(column, lookup) for column in columns]


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_column_type_repr(type_obj: object) -> str:
    if type_obj is None:
        return ""

    type_repr = str(type_obj)
    if "(" in type_repr and ")" in type_repr:
        return type_repr

    raw = type_repr.lower()
    if not any(token in raw for token in ("number", "numeric", "decimal")):
        return type_repr

    precision = _safe_int(getattr(type_obj, "precision", None))
    scale = _safe_int(getattr(type_obj, "scale", None))
    if precision is None:
        return type_repr
    if scale is None:
        return f"{type_repr}({precision})"
    return f"{type_repr}({precision},{scale})"


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


def _table_ref_for_error(table_name: str, schema: str | None) -> str:
    if schema:
        return f"{schema}.{table_name}"
    return table_name


def _validate_supported_output_column_kinds(
    *,
    selected_columns: Sequence[str],
    column_kinds: dict[str, ValueKind],
    column_type_repr: dict[str, str],
    table_name: str,
    schema: str | None,
) -> None:
    unsupported_columns = [
        column
        for column in selected_columns
        if column_kinds.get(column, ValueKind.UNKNOWN) not in SUPPORTED_OUTPUT_VALUE_KINDS
    ]
    if not unsupported_columns:
        return

    details = {
        column: {
            "kind": column_kinds.get(column, ValueKind.UNKNOWN).value,
            "type": column_type_repr.get(column, ""),
        }
        for column in unsupported_columns
    }
    raise ReadV3PlanningError(
        "Strict read_v3 could not infer output column kinds in table mode: "
        f"table={_table_ref_for_error(table_name, schema)!r}, columns={details!r}. "
        "Use explicit SQL casts in query mode for unsupported columns."
    )


def _validate_partition_key_kind(
    *,
    key_kind: ValueKind,
    table_name: str,
    schema: str | None,
    candidate_key: str,
    key_type_repr: str,
) -> None:
    if key_kind == ValueKind.JSON:
        raise ReadV3PlanningError(
            "Strict read_v3 does not support JSON partition keys in table mode: "
            f"table={_table_ref_for_error(table_name, schema)!r}, "
            f"column={candidate_key!r}, kind={key_kind.value!r}, type={key_type_repr!r}. "
            "Choose a scalar partition column or switch to query mode with an explicit cast."
        )


class TableReadPlanner:
    def build_plan(
        self,
        engine: Engine,
        table_name: str,
        *,
        min_rows_per_partition: int,
        target_partition_mem_mb: int,
        partitioning_overhead_coef: float,
        max_partitions: int,
        schema: str | None = None,
        columns: Sequence[str] | None = None,
        partition_col: str | None = None,
        npartitions: int | None = None,
        limit: int | None = None,
        max_rows_per_partition: int | None = None,
        partition_grouping: dict | None = None,
        partition_granularity: str | None = None,
        datetime_precision: ReadV3DateTimePrecision | str | None = None,
    ) -> ReadV3Plan:
        resolved_datetime_precision = normalize_datetime_precision(datetime_precision)
        grouping_spec = _grouping_mode(partition_grouping)
        if partition_granularity is not None and (
            grouping_spec is None or grouping_spec.mode != "granularity"
        ):
            raise ReadV3ConfigError(
                "partition_granularity requires partition_grouping.mode='granularity' in read_v3"
            )

        dialect = resolve_dialect(engine)
        inspector = inspect(engine)
        columns_info = inspector.get_columns(table_name, schema=schema)
        if not columns_info:
            raise ReadV3PlanningError(
                f"Failed to introspect table {table_name!r} (schema={schema!r}); no columns found"
            )

        actual_columns = [str(column["name"]) for column in columns_info]
        lookup = _build_lookup(actual_columns)

        selected_columns = (
            _ensure_columns_exist(columns, lookup) if columns else list(actual_columns)
        )

        candidate_key: str | None = None
        if partition_col:
            candidate_key = _resolve_column(partition_col, lookup)
        else:
            pk = (
                inspector.get_pk_constraint(table_name, schema=schema).get("constrained_columns")
                or []
            )
            if len(pk) == 1:
                reflected_pk = dialect.normalize_reflected_identifier(str(pk[0]))
                candidate_key = _resolve_column(reflected_pk, lookup)

        if candidate_key is None:
            raise ReadV3ConfigError(
                "Partition key is required in read_v3 strict mode. "
                "Provide partition_col or ensure table has a single-column PK."
            )

        key_type_repr = ""
        column_kinds: dict[str, ValueKind] = {}
        column_type_repr: dict[str, str] = {}
        mssql_type_reprs = (
            describe_mssql_table_column_types(
                engine,
                table_name=table_name,
                schema=schema,
            )
            if dialect.name == "mssql"
            else {}
        )
        for column in columns_info:
            column_name = str(column.get("name"))
            type_repr = _normalize_column_type_repr(column.get("type"))
            if dialect.detect_value_kind(type_repr) == ValueKind.UNKNOWN:
                type_repr = mssql_type_reprs.get(column_name.lower(), type_repr)
            column_type_repr[column_name] = type_repr
            column_kinds[column_name] = dialect.detect_value_kind(type_repr)
            if column_name == candidate_key:
                key_type_repr = type_repr

        key_kind = dialect.detect_value_kind(key_type_repr)
        _validate_supported_output_column_kinds(
            selected_columns=selected_columns,
            column_kinds=column_kinds,
            column_type_repr=column_type_repr,
            table_name=table_name,
            schema=schema,
        )
        _validate_partition_key_kind(
            key_kind=key_kind,
            table_name=table_name,
            schema=schema,
            candidate_key=candidate_key,
            key_type_repr=key_type_repr,
        )
        if key_kind == ValueKind.UNKNOWN:
            raise ReadV3PlanningError(
                "Strict read_v3 could not infer partition key kind in table mode: "
                f"table={_table_ref_for_error(table_name, schema)!r}, "
                f"column={candidate_key!r}, kind={key_kind.value!r}, type={key_type_repr!r}. "
                "Use a partition column with deterministic DB type."
            )
        relation_sql = f"FROM {dialect.full_table_name(table_name, schema)}"
        key_sql = dialect.quote_ident(candidate_key)
        relation_sql = _apply_relation_limit(
            relation_sql=relation_sql,
            key_sql=key_sql,
            limit=limit,
            dialect=dialect,
        )

        min_v, max_v, total_rows, non_null_rows = query_row_stats(
            engine=engine,
            dialect=dialect,
            cte_prefix_sql=None,
            relation_sql=relation_sql,
            key_sql=key_sql,
        )
        has_nulls = non_null_rows < total_rows
        auto_partition_estimate = None
        if npartitions is None:
            auto_partition_estimate = estimate_table_partitions(
                engine=engine,
                dialect=dialect,
                table_name=table_name,
                schema=schema,
                selected_columns=selected_columns,
                columns_info=columns_info,
                effective_rows_est=total_rows,
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

        output_column_kinds = {
            column: column_kinds.get(column, ValueKind.UNKNOWN) for column in selected_columns
        }
        output_column_type_repr = {
            column: column_type_repr.get(column, "") for column in selected_columns
        }
        output_column_select_exprs = {
            column: dialect.output_select_expr(
                dialect.quote_ident(column),
                output_name=column,
                type_repr=output_column_type_repr.get(column, ""),
            )
            for column in selected_columns
        }

        select_exprs: list[str] = [output_column_select_exprs[column] for column in selected_columns]
        partition_key_alias = "__dvt_partition_key"
        hash_bucket_alias = "__dvt_partition_bucket"
        index_column_name = candidate_key
        adapter_reason = "custom grouping"

        if grouping_spec is not None and grouping_spec.mode not in {"range", "hash"}:
            grouping_result = build_grouping_segments(
                engine=engine,
                dialect=dialect,
                relation_sql=relation_sql,
                cte_prefix_sql=None,
                key_sql=key_sql,
                partition_key_name=candidate_key,
                value_kind=key_kind,
                partition_grouping=grouping_spec,
                total_rows=total_rows,
                npartitions=target_npartitions,
                limit=limit,
                partition_granularity=partition_granularity,
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
                    cte_prefix_sql=None,
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
            candidate_key not in selected_columns
            or dialect.requires_string_output_cast(key_type_repr)
        ):
            select_exprs.append(f"{key_sql} AS {dialect.quote_ident(partition_key_alias)}")
            index_column_name = partition_key_alias

        if strategy == PartitionStrategy.HASH and hash_sql is not None:
            select_exprs.append(f"{hash_sql} AS {dialect.quote_ident(hash_bucket_alias)}")
            if candidate_key not in selected_columns:
                select_exprs.append(f"{key_sql} AS {dialect.quote_ident(partition_key_alias)}")
            index_column_name = hash_bucket_alias

        if max_rows_per_partition is None:
            baseline = max(1, math.ceil(max(total_rows, 1) / max(target_npartitions, 1)))
            max_rows_per_partition = max(100_000, baseline * 4)

        if max_rows_per_partition <= 0:
            raise ReadV3ConfigError("max_rows_per_partition must be positive")

        return ReadV3Plan(
            mode=ReadMode.TABLE,
            dialect=dialect.name,
            cte_prefix_sql=None,
            relation_sql=relation_sql,
            select_exprs=select_exprs,
            output_columns=selected_columns,
            partition_key_name=candidate_key,
            partition_key_kind=key_kind,
            strategy=strategy,
            segments=segments,
            divisions=divisions,
            max_rows_per_partition=max_rows_per_partition,
            partition_key_type_repr=key_type_repr,
            partition_key_alias=partition_key_alias,
            hash_bucket_alias=hash_bucket_alias,
            index_column_name=index_column_name,
            total_rows=total_rows,
            npartitions=target_npartitions,
            output_column_kinds=output_column_kinds,
            output_column_type_repr=output_column_type_repr,
            output_column_sql_names={column: column for column in selected_columns},
            output_column_select_exprs=output_column_select_exprs,
            partition_key_sql_name=candidate_key,
            extra_warnings=[
                f"strategy_reason={adapter_reason}",
                f"key_type={key_type_repr}",
                f"limit={limit!r}",
                f"min={min_v!r}",
                f"max={max_v!r}",
                f"auto_npartitions={getattr(auto_partition_estimate, 'npartitions', None)!r}",
                f"auto_rows_per_part={getattr(auto_partition_estimate, 'rows_per_part', None)!r}",
                f"auto_bytes_per_row={getattr(auto_partition_estimate, 'bytes_per_row_est', None)!r}",
            ],
            source_table_name=table_name,
            source_schema_name=schema,
            datetime_precision=resolved_datetime_precision,
        )
