from datetime import date, datetime
from typing import Any

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
