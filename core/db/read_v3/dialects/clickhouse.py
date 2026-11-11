from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, override

from core.db.read_v3.dialects.base import SQLDialect


class ClickHouseDialect(SQLDialect):
    name = "clickhouse"

    def quote_ident(self, ident: str) -> str:
        escaped = ident.replace("`", "``")
        return f"`{escaped}`"

    def normalize_reflected_identifier(self, ident: str) -> str:
        # clickhouse-sqlalchemy may return PK/ORDER BY column names already
        # quoted, while get_columns() returns their raw names.
        if len(ident) >= 2 and ident.startswith("`") and ident.endswith("`"):
            return ident[1:-1].replace("``", "`")
        return ident

    def limit_offset(self, limit: int, offset: int) -> str:
        return f"LIMIT {limit} OFFSET {offset}"

    def render_literal(self, value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, datetime):
            if value.tzinfo is not None:
                value = value.replace(tzinfo=None)
            return f"toDateTime('{value.strftime('%Y-%m-%d %H:%M:%S')}')"
        if isinstance(value, date):
            return f"toDate('{value.strftime('%Y-%m-%d')}')"
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"

    def hash_expr(self, key_sql: str, buckets: int) -> str:
        return f"mod(cityHash64(ifNull(toString({key_sql}), '__NULL__')), {buckets})"

    def string_prefix_expr(self, col_expr: str, length: int, lower: bool) -> str:
        expr = f"substringUTF8({col_expr}, 1, {length})"
        return f"lowerUTF8({expr})" if lower else expr

    def quantile_expr(self, col_expr: str, quantile: float) -> str:
        return f"quantileExact({quantile})({col_expr})"

    @override
    def range_boundaries_query(
        self,
        relation_sql: str,
        key_sql: str,
        *,
        page_size: int,
        non_null_rows: int,
    ) -> str:
        # row_number() over one sort instead of quantilesExact: quantilesExact runs nth_element
        # per level (600 levels on 49.7M rows: 17-33 s against about 1 s) and rejects String,
        # UUID, Date32 and IPv4 keys. The one-row frame lets the window release sorted blocks.
        return (
            f"SELECT boundary_value FROM (SELECT {key_sql} AS boundary_value, "
            f"row_number() OVER (ORDER BY {key_sql} ASC "
            f"ROWS BETWEEN CURRENT ROW AND CURRENT ROW) AS dvt_rn {relation_sql} "
            f"WHERE {key_sql} IS NOT NULL) dvt_ranked "
            f"WHERE (dvt_rn - 1) % {page_size} = 0 ORDER BY dvt_rn"
        )

    def heaviest_value_query(self, relation_sql: str, key_sql: str) -> str:
        return (
            f"SELECT {key_sql} AS dvt_heavy_value, count() AS dvt_heavy_count {relation_sql} "
            f"GROUP BY {key_sql} ORDER BY dvt_heavy_count DESC LIMIT 1"
        )

    def table_sort_key_query(self, *, table_name: str, database: str | None) -> str:
        database_sql = self.render_literal(database) if database else "currentDatabase()"
        return (
            "SELECT sorting_key, primary_key, sampling_key FROM system.tables "
            f"WHERE database = {database_sql} AND name = {self.render_literal(table_name)}"
        )

    def key_stats_query(self, relation_sql: str, columns: Sequence[tuple[str, str]]) -> str:
        # One GROUP BY per column, all branches in one statement: exact distinct count, heaviest
        # value with its count, NULL group size, min/max and row total.
        branches = [
            f"SELECT {self.render_literal(name)} AS column_name, "
            "countIf(isNotNull(dvt_kv)) AS distinct_count, "
            "maxIf(dvt_kc, isNotNull(dvt_kv)) AS max_repeat, "
            "CAST(toString(argMaxIf(dvt_kv, dvt_kc, isNotNull(dvt_kv))) AS Nullable(String)) "
            "AS max_repeat_value, "
            "sumIf(dvt_kc, isNull(dvt_kv)) AS null_count, "
            "CAST(toString(min(dvt_kv)) AS Nullable(String)) AS min_value, "
            "CAST(toString(max(dvt_kv)) AS Nullable(String)) AS max_value, "
            "sum(dvt_kc) AS total_rows "
            f"FROM (SELECT {key_sql} AS dvt_kv, count() AS dvt_kc {relation_sql} GROUP BY dvt_kv)"
            for name, key_sql in columns
        ]
        return " UNION ALL ".join(branches)

    def key_aggregates_query(self, relation_sql: str, columns: Sequence[tuple[str, str]]) -> str:
        # One streaming pass: approximate distinct (uniq), exact NULL count and min/max.
        parts = ["count() AS total_rows"]
        for idx, (_name, key_sql) in enumerate(columns):
            parts.extend(
                [
                    f"uniq({key_sql}) AS distinct_{idx}",
                    f"countIf(isNull({key_sql})) AS nulls_{idx}",
                    f"CAST(toString(min({key_sql})) AS Nullable(String)) AS min_{idx}",
                    f"CAST(toString(max({key_sql})) AS Nullable(String)) AS max_{idx}",
                ]
            )
        return f"SELECT {', '.join(parts)} {relation_sql}"

    @override
    def key_sample_relation(
        self,
        *,
        table_sql: str | None,
        select_list_sql: str,
        relation_sql: str,
        sample_rows: int,
        total_rows: int,
        native_sampling: bool = False,
    ) -> tuple[str, str]:
        if table_sql is not None and native_sampling:
            # MergeTree SAMPLE BY: reads only part of the data.
            return (
                f"FROM (SELECT {select_list_sql} FROM {table_sql} SAMPLE {int(sample_rows)}) "
                "dvt_key_sample",
                "clickhouse_sample",
            )
        # rand() is a uniform UInt32: the filter keeps about sample_rows rows of one full pass.
        fraction = min(1.0, sample_rows / max(total_rows, 1))
        threshold = max(1, int(fraction * 4_294_967_296))
        return (
            f"FROM (SELECT {select_list_sql} {relation_sql} WHERE rand() < {threshold}) "
            "dvt_key_sample",
            "random_filter",
        )
