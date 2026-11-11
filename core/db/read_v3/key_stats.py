"""Partition-key statistics of a read_v3 relation: a table, or a query embedded as ``user_query``.

``collect_key_statistics`` profiles candidate partition columns the way the planners address the
relation (same quoting, same ``user_query`` CTE) and returns plain dataclasses:

- relation totals: rows, estimated bytes per row of the read columns (the planner's width
  estimation), the physical sort key and index-leading columns where the dialect exposes them;
- per column: type, distinct count, the most repeated value and its count, NULL count, min/max.

How the numbers are obtained (``ColumnKeyStats.source``):

- ``exact``: the relation has at most ``sample_rows`` rows; every row is grouped by value;
- ``approximate`` (ClickHouse above the threshold): one streaming pass gives ``uniq`` distinct,
  exact NULL count and min/max; the heaviest value is counted in a sample and scaled;
- ``catalog`` (PostgreSQL tables above the threshold): ``pg_stats`` from the last ANALYZE;
- ``sample`` (other dialects above the threshold, query mode, columns without catalog rows):
  value groups of a sample (TABLESAMPLE/SAMPLE where available, otherwise the first rows),
  counts scaled to the relation; the distinct count is the one seen in the sample.

Everything except ``exact`` is marked ``estimated``. ``query_df`` lets the caller run every data
query (for example in a read-only session with a statement timeout); metadata lookups (column
reflection, catalog row counts, sort keys) use the engine directly.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

import pandas as pd
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from core.db.read_v3._auto_partition import (
    _table_bytes_and_rows,
    estimate_query_bytes_per_row,
    estimate_table_bytes_per_row,
)
from core.db.read_v3.dialects import resolve_dialect
from core.db.read_v3.dialects.base import SQLDialect
from core.db.read_v3.embedded_query import build_read_v3_query_embedding
from core.db.read_v3.errors import ReadV3ConfigError, ReadV3PlanningError
from core.db.read_v3.models import ReadMode, ValueKind
from core.db.read_v3.planner.key_skew import (
    CatalogColumnStats,
    first_row,
    plain_value,
    read_catalog_column_stats,
    with_cte,
)
from core.db.read_v3.planner.query import _infer_kind_from_value, _resolve_public_query_columns
from core.db.read_v3.planner.table import _normalize_column_type_repr
from core.db.read_v3.query_metadata import (
    describe_mssql_table_column_types,
    describe_query_columns,
)
from core.db.read_v3.sql_runner import read_sql_df

QueryDf = Callable[[str], pd.DataFrame]

# Kinds a partition key can have in a useful plan. BOOL has at most two values, JSON is rejected
# by the planners; UNKNOWN is profiled only in query mode, where the kind is inferred from values.
KEY_VALUE_KINDS = frozenset(
    {ValueKind.NUMERIC, ValueKind.DATE, ValueKind.DATETIME, ValueKind.STRING, ValueKind.UUID}
)
DEFAULT_CANDIDATE_LIMIT = 20
# Row counts from these catalogs are estimates (pg_class.reltuples, information_schema).
_ESTIMATED_ROW_COUNT_DIALECTS = frozenset({"postgresql", "mysql"})


class KeyStatsSource(StrEnum):
    EXACT = "exact"
    APPROXIMATE = "approximate"
    CATALOG = "catalog"
    SAMPLE = "sample"


@dataclass(frozen=True)
class ColumnKeyStats:
    name: str
    type_repr: str
    value_kind: ValueKind
    available: bool
    source: KeyStatsSource | None = None
    estimated: bool = False
    distinct_count: int | None = None
    max_repeat: int | None = None
    max_repeat_value: Any = None
    null_count: int | None = None
    min_value: Any = None
    max_value: Any = None
    # Leading column of the physical sort key (ClickHouse), the primary key or an index.
    indexed: bool = False
    note: str | None = None


@dataclass(frozen=True)
class RelationKeyStats:
    mode: ReadMode
    dialect: str
    relation: str
    total_rows: int
    total_rows_estimated: bool
    bytes_per_row_est: int
    read_columns: tuple[str, ...]
    sort_key: str | None
    # None when every candidate was profiled exactly.
    sample_method: str | None
    sample_rows: int | None
    sample_threshold_rows: int
    columns: tuple[ColumnKeyStats, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Column:
    name: str
    sql: str
    type_repr: str
    kind: ValueKind


@dataclass
class _Relation:
    mode: ReadMode
    name: str
    cte_prefix_sql: str | None
    relation_sql: str
    table_sql: str | None
    table_name: str | None
    schema: str | None
    columns: list[_Column]
    read_columns: tuple[str, ...]
    total_rows: int
    total_rows_estimated: bool
    bytes_per_row_est: int
    sort_key: str | None = None
    native_sampling: bool = False
    indexed: frozenset[str] = frozenset()
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Profile:
    columns: dict[str, ColumnKeyStats]
    sample_method: str | None = None
    sample_rows: int | None = None
    # Row count measured by a full pass, replacing a catalog estimate.
    total_rows: int | None = None
    warnings: list[str] = field(default_factory=list)


def _int_or_none(value: Any) -> int | None:
    value = plain_value(value)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_value(value: Any, kind: ValueKind) -> Any:
    """Typed value from a driver value or its text form (ClickHouse toString, pg_stats)."""
    value = plain_value(value)
    if not isinstance(value, str):
        return value
    result: Any = value
    try:
        if kind == ValueKind.NUMERIC:
            result = int(value) if value.lstrip("+-").isdigit() else float(value)
        elif kind == ValueKind.DATE:
            result = date.fromisoformat(value[:10])
        elif kind == ValueKind.DATETIME:
            parsed = pd.to_datetime(value)
            if isinstance(parsed, pd.Timestamp):
                result = parsed.to_pydatetime()
    except (TypeError, ValueError, OverflowError):
        result = value
    return result


def _scaled(count: int | None, scale: float) -> int | None:
    if count is None:
        return None
    return round(count * scale)


def _resolve_names(requested: Sequence[str], columns: Sequence[_Column]) -> list[_Column]:
    by_lower = {column.name.lower(): column for column in columns}
    resolved: list[_Column] = []
    for name in requested:
        column = by_lower.get(str(name).lower())
        if column is None:
            raise ReadV3PlanningError(
                f"Column {name!r} was not found in relation columns "
                f"{[item.name for item in columns]!r}"
            )
        if column not in resolved:
            resolved.append(column)
    return resolved


def _split_top_level(expr: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in expr:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    if "".join(current).strip():
        parts.append("".join(current).strip())
    return parts


def _leading_sort_column(sort_key: str | None) -> str | None:
    """First bare column of a ClickHouse key expression; None for an expression or no key."""
    parts = _split_top_level((sort_key or "").strip())
    if not parts:
        return None
    first = parts[0]
    if len(first) >= 2 and first.startswith("`") and first.endswith("`"):
        return first[1:-1].replace("``", "`")
    if all(char.isalnum() or char in "_$" for char in first):
        return first
    return None


def _table_sort_key(
    engine: Engine,
    dialect: SQLDialect,
    *,
    table_name: str,
    schema: str | None,
    run: QueryDf,
) -> tuple[str | None, bool, set[str]]:
    """Return ``(sort_key text, has sampling key, index-leading column names)``."""
    try:
        sql = dialect.table_sort_key_query(
            table_name=table_name,
            database=schema or engine.url.database,
        )
    except NotImplementedError:
        sql = None
    if sql is not None:
        df = run(sql)
        if df.empty:
            return None, False, set()
        row = first_row(df)
        sort_key = str(plain_value(row.get("sorting_key")) or "") or None
        primary_key = str(plain_value(row.get("primary_key")) or "") or None
        sampling_key = str(plain_value(row.get("sampling_key")) or "")
        leading = {
            column
            for column in (_leading_sort_column(sort_key), _leading_sort_column(primary_key))
            if column
        }
        return sort_key, bool(sampling_key), leading

    inspector = inspect(engine)
    leading: set[str] = set()
    pk_columns = inspector.get_pk_constraint(table_name, schema=schema).get("constrained_columns")
    if pk_columns:
        leading.add(dialect.normalize_reflected_identifier(str(pk_columns[0])))
    for index in inspector.get_indexes(table_name, schema=schema):
        column_names = [name for name in index.get("column_names") or [] if name]
        using = (index.get("dialect_options") or {}).get("postgresql_using")
        if column_names and using in (None, "btree"):
            leading.add(dialect.normalize_reflected_identifier(str(column_names[0])))
    sort_key = ", ".join(str(column) for column in pk_columns) if pk_columns else None
    return sort_key, False, leading


def _table_relation(
    engine: Engine,
    dialect: SQLDialect,
    run: QueryDf,
    *,
    table_name: str,
    schema: str | None,
    read_columns: Sequence[str] | None,
) -> _Relation:
    columns_info = inspect(engine).get_columns(table_name, schema=schema)
    if not columns_info:
        raise ReadV3PlanningError(
            f"Failed to introspect table {table_name!r} (schema={schema!r}); no columns found"
        )
    mssql_type_reprs = (
        describe_mssql_table_column_types(engine, table_name=table_name, schema=schema)
        if dialect.name == "mssql"
        else {}
    )
    columns: list[_Column] = []
    for info in columns_info:
        name = str(info["name"])
        type_repr = _normalize_column_type_repr(info.get("type"))
        if dialect.detect_value_kind(type_repr) == ValueKind.UNKNOWN:
            type_repr = mssql_type_reprs.get(name.lower(), type_repr)
        columns.append(
            _Column(
                name=name,
                sql=dialect.quote_ident(name),
                type_repr=type_repr,
                kind=dialect.detect_value_kind(type_repr),
            )
        )
    selected = _resolve_names(read_columns, columns) if read_columns else list(columns)
    table_sql = dialect.full_table_name(table_name, schema)
    relation_sql = f"FROM {table_sql}"
    warnings: list[str] = []

    try:
        _, total_rows = _table_bytes_and_rows(engine, dialect, table_name, schema)
    except Exception:
        total_rows = None
    total_rows_estimated = dialect.name in _ESTIMATED_ROW_COUNT_DIALECTS
    if total_rows is None or total_rows <= 0:
        total_rows = _int_or_none(run(f"SELECT COUNT(*) AS total_rows {relation_sql}").iloc[0, 0])
        total_rows_estimated = False
    bytes_per_row_est = estimate_table_bytes_per_row(
        engine=engine,
        dialect=dialect,
        table_name=table_name,
        schema=schema,
        selected_columns=[column.name for column in selected],
        columns_info=columns_info,
    )
    try:
        sort_key, native_sampling, indexed = _table_sort_key(
            engine, dialect, table_name=table_name, schema=schema, run=run
        )
    except Exception as exc:
        sort_key, native_sampling, indexed = None, False, set()
        warnings.append(f"sort key and index lookup failed ({type(exc).__name__})")
    indexed_lower = {name.lower() for name in indexed}
    return _Relation(
        mode=ReadMode.TABLE,
        name=f"{schema}.{table_name}" if schema else table_name,
        cte_prefix_sql=None,
        relation_sql=relation_sql,
        table_sql=table_sql,
        table_name=table_name,
        schema=schema,
        columns=columns,
        read_columns=tuple(column.name for column in selected),
        total_rows=int(total_rows or 0),
        total_rows_estimated=total_rows_estimated,
        bytes_per_row_est=bytes_per_row_est,
        sort_key=sort_key,
        native_sampling=native_sampling,
        indexed=frozenset(
            column.name for column in columns if column.name.lower() in indexed_lower
        ),
        warnings=warnings,
    )


def _query_relation(
    engine: Engine,
    dialect: SQLDialect,
    run: QueryDf,
    *,
    query: str,
    read_columns: Sequence[str] | None,
) -> _Relation:
    normalized_query = query.strip().rstrip(";")
    if not normalized_query:
        raise ReadV3ConfigError("query is empty")
    try:
        embedding = build_read_v3_query_embedding(normalized_query, dialect_name=dialect.name)
    except ValueError as exc:
        raise ReadV3ConfigError(str(exc)) from exc
    cte_prefix_sql = embedding.cte_prefix_sql
    relation_sql = embedding.relation_sql

    meta_df = run(f"{cte_prefix_sql} SELECT * {relation_sql} WHERE 1=0")
    result_columns = [str(column) for column in meta_df.columns]
    described = describe_query_columns(engine, normalized_query)
    if not result_columns and described:
        result_columns = [str(name) for name, _ in described]
    if not result_columns:
        raise ReadV3PlanningError("Query does not expose columns; cannot profile partition keys")
    public_columns = _resolve_public_query_columns(result_columns, described)
    type_by_lower = {str(name).lower(): type_repr for name, type_repr in described}
    sql_name_by_lower = {str(name).lower(): str(name) for name, _ in described}
    columns = [
        _Column(
            name=name,
            sql=dialect.quote_result_column(sql_name_by_lower.get(name.lower(), name)),
            type_repr=type_by_lower.get(name.lower(), ""),
            kind=dialect.detect_value_kind(type_by_lower.get(name.lower(), "")),
        )
        for name in public_columns
    ]
    selected = _resolve_names(read_columns, columns) if read_columns else list(columns)
    total_rows = _int_or_none(
        run(f"{cte_prefix_sql} SELECT COUNT(*) AS total_rows {relation_sql}").iloc[0, 0]
    )
    bytes_per_row_est = estimate_query_bytes_per_row(
        engine=engine,
        dialect=dialect,
        cte_prefix_sql=cte_prefix_sql,
        relation_sql=relation_sql,
        selected_sql_columns=[sql_name_by_lower.get(c.name.lower(), c.name) for c in selected],
        output_column_type_repr={column.name: column.type_repr for column in selected},
        query_df=run,
    )
    return _Relation(
        mode=ReadMode.QUERY,
        name="user_query",
        cte_prefix_sql=cte_prefix_sql,
        relation_sql=relation_sql,
        table_sql=None,
        table_name=None,
        schema=None,
        columns=columns,
        read_columns=tuple(column.name for column in selected),
        total_rows=int(total_rows or 0),
        total_rows_estimated=False,
        bytes_per_row_est=bytes_per_row_est,
    )


def _candidates(
    relation: _Relation,
    columns: Sequence[str] | None,
    candidate_limit: int,
) -> tuple[list[_Column], list[ColumnKeyStats]]:
    def profilable(column: _Column) -> bool:
        return column.kind in KEY_VALUE_KINDS or (
            relation.mode == ReadMode.QUERY and column.kind == ValueKind.UNKNOWN
        )

    if columns:
        chosen = _resolve_names(columns, relation.columns)
    else:
        scalar = [column for column in relation.columns if profilable(column)]
        # Sort-key/index-leading columns first: they are the cheapest range keys.
        scalar.sort(key=lambda column: column.name not in relation.indexed)
        chosen = scalar[:candidate_limit]
    unsupported = [
        ColumnKeyStats(
            name=column.name,
            type_repr=column.type_repr,
            value_kind=column.kind,
            available=False,
            indexed=column.name in relation.indexed,
            note=(
                f"type {column.type_repr!r} ({column.kind.value}) is not usable as a partition key"
            ),
        )
        for column in chosen
        if not profilable(column)
    ]
    return [column for column in chosen if profilable(column)], unsupported


def _zero_profile(relation: _Relation, candidates: Sequence[_Column]) -> _Profile:
    return _Profile(
        columns={
            column.name: ColumnKeyStats(
                name=column.name,
                type_repr=column.type_repr,
                value_kind=column.kind,
                available=True,
                source=KeyStatsSource.EXACT,
                distinct_count=0,
                max_repeat=0,
                null_count=0,
                indexed=column.name in relation.indexed,
            )
            for column in candidates
        }
    )


def _clickhouse_profile(
    dialect: SQLDialect,
    run: QueryDf,
    relation: _Relation,
    candidates: Sequence[_Column],
    *,
    sample_rows: int,
) -> _Profile:
    pairs = [(column.name, column.sql) for column in candidates]
    cte = relation.cte_prefix_sql
    exact = relation.total_rows <= sample_rows
    if exact:
        group_rel, method = relation.relation_sql, None
    else:
        group_rel, method = dialect.key_sample_relation(
            table_sql=relation.table_sql,
            select_list_sql=", ".join(column.sql for column in candidates),
            relation_sql=relation.relation_sql,
            sample_rows=sample_rows,
            total_rows=relation.total_rows,
            native_sampling=relation.native_sampling,
        )
    groups = {
        str(row["column_name"]): row
        for row in run(with_cte(cte, dialect.key_stats_query(group_rel, pairs))).to_dict("records")
    }
    aggregates = (
        None
        if exact
        else first_row(
            run(with_cte(cte, dialect.key_aggregates_query(relation.relation_sql, pairs)))
        )
    )
    total_rows = (
        int(next(iter(groups.values()))["total_rows"]) if exact else int(aggregates["total_rows"])
    )
    profile = _Profile(columns={})
    for idx, column in enumerate(candidates):
        row = groups[column.name]
        group_total = int(row["total_rows"])
        has_values = int(row["distinct_count"]) > 0
        common = {
            "name": column.name,
            "type_repr": column.type_repr,
            "value_kind": column.kind,
            "available": True,
            "indexed": column.name in relation.indexed,
            "max_repeat_value": _coerce_value(row["max_repeat_value"], column.kind)
            if has_values
            else None,
        }
        if exact:
            profile.columns[column.name] = ColumnKeyStats(
                **common,
                source=KeyStatsSource.EXACT,
                distinct_count=int(row["distinct_count"]),
                max_repeat=int(row["max_repeat"]),
                null_count=int(row["null_count"]),
                min_value=_coerce_value(row["min_value"], column.kind) if has_values else None,
                max_value=_coerce_value(row["max_value"], column.kind) if has_values else None,
            )
            continue
        scale = total_rows / group_total if group_total else 0.0
        profile.columns[column.name] = ColumnKeyStats(
            **common,
            source=KeyStatsSource.APPROXIMATE,
            estimated=True,
            distinct_count=int(aggregates[f"distinct_{idx}"]),
            max_repeat=_scaled(int(row["max_repeat"]), scale),
            null_count=int(aggregates[f"nulls_{idx}"]),
            min_value=_coerce_value(aggregates[f"min_{idx}"], column.kind),
            max_value=_coerce_value(aggregates[f"max_{idx}"], column.kind),
            note=(
                f"distinct: uniq() over all rows; NULLs, min/max: exact; heaviest value: counted "
                f"in a {method} sample of {group_total} rows and scaled"
            ),
        )
        profile.sample_rows = group_total
    profile.sample_method = method
    profile.total_rows = total_rows
    return profile


def _from_catalog(
    column: _Column,
    catalog: CatalogColumnStats,
    relation: _Relation,
) -> ColumnKeyStats:
    total_rows = relation.total_rows
    null_count = round(catalog.null_frac * total_rows) if catalog.null_frac is not None else None
    distinct: int | None = None
    if catalog.n_distinct is not None and catalog.n_distinct > 0:
        distinct = round(catalog.n_distinct)
    elif catalog.n_distinct is not None and catalog.n_distinct < 0:
        distinct = round(-catalog.n_distinct * total_rows)
    non_null = max(0, total_rows - (null_count or 0))
    note = "pg_stats from the last ANALYZE; min/max are histogram ends"
    if catalog.top_freq is not None:
        max_repeat = round(catalog.top_freq * total_rows)
        max_repeat_value = _coerce_value(catalog.top_value, column.kind)
    else:
        max_repeat = math.ceil(non_null / distinct) if distinct else None
        max_repeat_value = None
        note += "; no most common values listed, heaviest count assumes an even spread"
    return ColumnKeyStats(
        name=column.name,
        type_repr=column.type_repr,
        value_kind=column.kind,
        available=True,
        source=KeyStatsSource.CATALOG,
        estimated=True,
        distinct_count=distinct,
        max_repeat=max_repeat,
        max_repeat_value=max_repeat_value,
        null_count=null_count,
        min_value=_coerce_value(catalog.hist_min, column.kind),
        max_value=_coerce_value(catalog.hist_max, column.kind),
        indexed=column.name in relation.indexed,
        note=note,
    )


def _profile_one(
    dialect: SQLDialect,
    run: QueryDf,
    relation: _Relation,
    column: _Column,
    relation_sql: str,
) -> tuple[dict[str, Any], pd.DataFrame]:
    cte = relation.cte_prefix_sql
    profile_row = first_row(run(with_cte(cte, dialect.key_profile_query(relation_sql, column.sql))))
    top_df = run(with_cte(cte, dialect.key_top_value_query(relation_sql, column.sql)))
    return profile_row, top_df


def _generic_profile(
    dialect: SQLDialect,
    run: QueryDf,
    relation: _Relation,
    candidates: Sequence[_Column],
    *,
    sample_rows: int,
) -> _Profile:
    profile = _Profile(columns={})
    exact = relation.total_rows <= sample_rows
    remaining = list(candidates)
    if not exact and relation.mode == ReadMode.TABLE and relation.table_name:
        try:
            catalog = read_catalog_column_stats(
                dialect=dialect,
                table_name=relation.table_name,
                schema=relation.schema,
                column_names=[column.name for column in candidates],
                query_df=run,
            )
        except Exception as exc:
            catalog = None
            profile.warnings.append(f"catalog statistics lookup failed ({type(exc).__name__})")
        for column in candidates:
            if catalog and column.name in catalog:
                profile.columns[column.name] = _from_catalog(column, catalog[column.name], relation)
        remaining = [column for column in candidates if column.name not in profile.columns]
    from_catalog = len(candidates) - len(remaining)
    if not remaining:
        profile.sample_method = "pg_stats"
        return profile

    sample_args = {
        "table_sql": relation.table_sql,
        "select_list_sql": ", ".join(column.sql for column in remaining),
        "relation_sql": relation.relation_sql,
        "sample_rows": sample_rows,
        "total_rows": relation.total_rows,
        "native_sampling": relation.native_sampling,
    }
    if exact:
        relation_sql, method = relation.relation_sql, None
    else:
        relation_sql, method = dialect.key_sample_relation(**sample_args)
    for column in remaining:
        try:
            profile_row, top_df = _profile_one(dialect, run, relation, column, relation_sql)
        except Exception as exc:
            if method is None or method == "first_rows":
                profile.columns[column.name] = ColumnKeyStats(
                    name=column.name,
                    type_repr=column.type_repr,
                    value_kind=column.kind,
                    available=False,
                    indexed=column.name in relation.indexed,
                    note=f"statistics query failed ({type(exc).__name__})",
                )
                continue
            # The dialect sample clause may not apply (for example to a view): use first rows.
            relation_sql, method = SQLDialect.key_sample_relation(dialect, **sample_args)
            profile.warnings.append(
                f"sampling clause failed ({type(exc).__name__}); used the first rows instead"
            )
            try:
                profile_row, top_df = _profile_one(dialect, run, relation, column, relation_sql)
            except Exception as retry_exc:
                profile.columns[column.name] = ColumnKeyStats(
                    name=column.name,
                    type_repr=column.type_repr,
                    value_kind=column.kind,
                    available=False,
                    indexed=column.name in relation.indexed,
                    note=f"statistics query failed ({type(retry_exc).__name__})",
                )
                continue
        profile.columns[column.name] = _from_groups(
            column, relation, profile_row, top_df, exact=exact, method=method
        )
        if exact:
            profile.total_rows = _int_or_none(profile_row.get("total_rows"))
        else:
            profile.sample_rows = _int_or_none(profile_row.get("total_rows"))
    if method is not None:
        profile.sample_method = f"pg_stats+{method}" if from_catalog else method
    return profile


def _from_groups(
    column: _Column,
    relation: _Relation,
    profile_row: dict[str, Any],
    top_df: pd.DataFrame,
    *,
    exact: bool,
    method: str | None,
) -> ColumnKeyStats:
    group_total = _int_or_none(profile_row.get("total_rows")) or 0
    top_row = None if top_df.empty else first_row(top_df)
    top_count = None if top_row is None else _int_or_none(top_row["top_count"])
    top_value = None if top_row is None else plain_value(top_row["top_value"])
    min_value = plain_value(profile_row.get("min_value"))
    kind = column.kind
    if kind == ValueKind.UNKNOWN:
        inferred = _infer_kind_from_value(min_value if min_value is not None else top_value)
        kind = inferred if inferred != ValueKind.JSON else ValueKind.UNKNOWN
    common = {
        "name": column.name,
        "type_repr": column.type_repr,
        "value_kind": kind,
        "indexed": column.name in relation.indexed,
        "max_repeat_value": _coerce_value(top_value, kind),
        "min_value": _coerce_value(min_value, kind),
        "max_value": _coerce_value(profile_row.get("max_value"), kind),
    }
    if exact:
        return ColumnKeyStats(
            **common,
            available=True,
            source=KeyStatsSource.EXACT,
            distinct_count=_int_or_none(profile_row.get("distinct_count")),
            max_repeat=top_count or 0,
            null_count=_int_or_none(profile_row.get("null_count")),
        )
    if group_total <= 0:
        return ColumnKeyStats(
            **common,
            available=False,
            note=f"the {method} sample returned no rows",
        )
    scale = relation.total_rows / group_total
    return ColumnKeyStats(
        **common,
        available=True,
        source=KeyStatsSource.SAMPLE,
        estimated=True,
        distinct_count=_int_or_none(profile_row.get("distinct_count")),
        max_repeat=_scaled(top_count or 0, scale),
        null_count=_scaled(_int_or_none(profile_row.get("null_count")), scale),
        note=(
            f"{method} sample of {group_total} rows; counts scaled to the relation, "
            "distinct counted in the sample"
        ),
    )


def collect_key_statistics(
    engine: Engine,
    *,
    sample_rows: int,
    table_name: str | None = None,
    schema: str | None = None,
    query: str | None = None,
    columns: Sequence[str] | None = None,
    read_columns: Sequence[str] | None = None,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    query_df: QueryDf | None = None,
) -> RelationKeyStats:
    """Profile candidate partition columns of a table (``table_name``) or a query (``query``).

    ``columns`` are the candidates (default: up to ``candidate_limit`` scalar columns,
    sort-key/index-leading ones first); ``read_columns`` are the columns the reader selects,
    used for the row-width estimate (default: all). ``sample_rows`` is the exact-profiling
    threshold and the sample size above it.
    """
    if (table_name is None) == (query is None):
        raise ReadV3ConfigError("Provide exactly one of table_name or query")
    if sample_rows <= 0:
        raise ReadV3ConfigError("sample_rows must be positive")
    if candidate_limit <= 0:
        raise ReadV3ConfigError("candidate_limit must be positive")
    dialect = resolve_dialect(engine)
    run: QueryDf = query_df or (lambda sql: read_sql_df(engine, sql))

    if table_name is not None:
        relation = _table_relation(
            engine, dialect, run, table_name=table_name, schema=schema, read_columns=read_columns
        )
    else:
        relation = _query_relation(
            engine, dialect, run, query=str(query), read_columns=read_columns
        )
    candidates, unsupported = _candidates(relation, columns, candidate_limit)

    if not candidates:
        profile = _Profile(columns={})
    elif relation.total_rows <= 0:
        profile = _zero_profile(relation, candidates)
    else:
        try:
            dialect.key_stats_query(relation.relation_sql, [])
        except NotImplementedError:
            profile = _generic_profile(dialect, run, relation, candidates, sample_rows=sample_rows)
        else:
            profile = _clickhouse_profile(
                dialect, run, relation, candidates, sample_rows=sample_rows
            )

    total_rows, total_rows_estimated = relation.total_rows, relation.total_rows_estimated
    if profile.total_rows is not None:
        total_rows, total_rows_estimated = profile.total_rows, False
    unsupported_by_name = {item.name: item for item in unsupported}
    ordered = [
        profile.columns.get(name) or unsupported_by_name[name]
        for name in [*(column.name for column in candidates), *unsupported_by_name]
    ]
    return RelationKeyStats(
        mode=relation.mode,
        dialect=dialect.name,
        relation=relation.name,
        total_rows=total_rows,
        total_rows_estimated=total_rows_estimated,
        bytes_per_row_est=relation.bytes_per_row_est,
        read_columns=relation.read_columns,
        sort_key=relation.sort_key,
        sample_method=profile.sample_method,
        sample_rows=profile.sample_rows,
        sample_threshold_rows=sample_rows,
        columns=tuple(ordered),
        warnings=(*relation.warnings, *profile.warnings),
    )
