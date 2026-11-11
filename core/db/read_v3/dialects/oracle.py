import re
from datetime import date, datetime
from typing import Any, override

from core.db.read_v3.dialects.base import SQLDialect

# Unquoted Oracle identifiers must start with a letter.
_SIMPLE_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")


class OracleDialect(SQLDialect):
    name = "oracle"

    def quote_ident(self, ident: str) -> str:
        ident = ident.strip()
        if ident == "" or ident == "*":
            return ident
        if ident.startswith('"') and ident.endswith('"'):
            return ident
        parts = ident.split(".")
        return ".".join(self._quote_part(part) for part in parts)

    def _quote_part(self, part: str) -> str:
        part = part.strip()
        if part == "" or part == "*":
            return part
        if _SIMPLE_IDENT.match(part):
            return part
        escaped = part.replace('"', '""')
        return f'"{escaped}"'

    def quote_result_column(self, ident: str) -> str:
        ident = ident.strip()
        if ident == "" or ident == "*":
            return ident
        if ident.startswith('"') and ident.endswith('"'):
            return ident
        if _SIMPLE_IDENT.match(ident) and (ident.islower() or ident.isupper()):
            return ident
        escaped = ident.replace('"', '""')
        return f'"{escaped}"'

    def limit_offset(self, limit: int, offset: int) -> str:
        return f"OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"

    def cap_rows_sql(self, sql: str, row_cap: int) -> str:
        if row_cap <= 0:
            raise ValueError("row_cap must be positive")
        normalized_sql = sql.strip().rstrip(";")
        # Oracle unquoted identifiers must start with a letter.
        return f"SELECT * FROM ({normalized_sql}) dvt_cap {self.limit_offset(row_cap, 0)}"

    def render_literal(self, value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, datetime):
            literal = value.strftime("%Y-%m-%d %H:%M:%S")
            if value.microsecond:
                literal = value.strftime("%Y-%m-%d %H:%M:%S.%f")
            return f"TIMESTAMP '{literal}'"
        if isinstance(value, date):
            return f"DATE '{value:%Y-%m-%d}'"
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"

    def hash_expr(self, key_sql: str, buckets: int) -> str:
        return f"MOD(ORA_HASH(COALESCE(TO_CHAR({key_sql}), '__NULL__')), {buckets})"

    def string_prefix_expr(self, col_expr: str, length: int, lower: bool) -> str:
        expr = f"SUBSTR({col_expr}, 1, {length})"
        return f"LOWER({expr})" if lower else expr

    @override
    def range_boundaries_query(
        self,
        relation_sql: str,
        key_sql: str,
        *,
        page_size: int,
        non_null_rows: int,
    ) -> str:
        return self.row_number_boundaries_query(relation_sql, key_sql, page_size)

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
        # Row sample; SEED keeps the same rows for every statistics query. Oracle needs < 100.
        percent = min(99.999999, max(0.000001, 100.0 * sample_rows / max(total_rows, 1)))
        return (
            f"FROM (SELECT {select_list_sql} FROM {table_sql} SAMPLE ({percent:.6f}) SEED (17)) "
            "dvt_key_sample",
            "sample_clause",
        )
