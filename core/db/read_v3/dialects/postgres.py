from collections.abc import Sequence
from typing import override

from core.db.read_v3.dialects.base import SQLDialect

# Seed of TABLESAMPLE ... REPEATABLE: every statistics query of one call sees the same blocks.
_SAMPLE_SEED = 17


class PostgresDialect(SQLDialect):
    name = "postgresql"

    def quote_ident(self, ident: str) -> str:
        escaped = ident.replace('"', '""')
        return f'"{escaped}"'

    def limit_offset(self, limit: int, offset: int) -> str:
        return f"LIMIT {limit} OFFSET {offset}"

    def hash_expr(self, key_sql: str, buckets: int) -> str:
        # Works for any type by converting the key to text explicitly.
        return f"mod(abs(hashtext(coalesce(({key_sql})::text, '__NULL__'))), {buckets})"

    def string_prefix_expr(self, col_expr: str, length: int, lower: bool) -> str:
        expr = f"substring({col_expr} from 1 for {length})"
        return f"lower({expr})" if lower else expr

    @override
    def range_boundaries_query(
        self,
        relation_sql: str,
        key_sql: str,
        *,
        page_size: int,
        non_null_rows: int,
    ) -> str:
        # percentile_disc(f) returns 1-based row max(1, ceil(f * N)) of the sorted keys; the
        # mid-rank fraction (rank + 0.5) / N therefore selects 0-based ``rank`` despite float
        # rounding, the same row as OFFSET rank.
        fractions = ", ".join(
            repr((rank + 0.5) / non_null_rows) for rank in range(0, non_null_rows, page_size)
        )
        return (
            "SELECT dvt_b.boundary_value FROM ("
            f"SELECT percentile_disc(ARRAY[{fractions}]::double precision[]) "
            f"WITHIN GROUP (ORDER BY {key_sql}) AS dvt_bounds {relation_sql} "
            f"WHERE {key_sql} IS NOT NULL) dvt_q "
            "CROSS JOIN LATERAL unnest(dvt_q.dvt_bounds) WITH ORDINALITY "
            "AS dvt_b(boundary_value, dvt_ord) ORDER BY dvt_b.dvt_ord"
        )

    def column_statistics_query(
        self,
        *,
        table_name: str,
        schema: str | None,
        column_names: Sequence[str],
    ) -> str:
        # ANALYZE statistics: the first most_common_vals entry is the most frequent value;
        # histogram_bounds exclude those values, so its ends only approximate min/max.
        schema_sql = self.render_literal(schema) if schema else "current_schema()"
        names_sql = self.render_in_list(list(column_names))
        return (
            "SELECT s.attname AS column_name, s.inherited AS inherited, "
            "s.null_frac AS null_frac, s.n_distinct AS n_distinct, "
            "(s.most_common_vals::text::text[])[1] AS top_value, "
            "s.most_common_freqs[1] AS top_freq, "
            "(s.histogram_bounds::text::text[])[1] AS hist_min, "
            "(s.histogram_bounds::text::text[])"
            "[cardinality(s.histogram_bounds::text::text[])] AS hist_max "
            "FROM pg_catalog.pg_stats s "
            f"WHERE s.schemaname = {schema_sql} AND s.tablename = {self.render_literal(table_name)} "
            f"AND s.attname IN ({names_sql})"
        )

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
        if table_sql is None:
            return super().key_sample_relation(
                table_sql=table_sql,
                select_list_sql=select_list_sql,
                relation_sql=relation_sql,
                sample_rows=sample_rows,
                total_rows=total_rows,
            )
        percent = min(100.0, max(0.0001, 100.0 * sample_rows / max(total_rows, 1)))
        return (
            f"FROM (SELECT {select_list_sql} FROM {table_sql} "
            f"TABLESAMPLE SYSTEM ({percent:.6f}) REPEATABLE ({_SAMPLE_SEED})) dvt_key_sample",
            "tablesample_system",
        )
