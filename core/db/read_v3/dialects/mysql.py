from typing import override

from core.db.read_v3.dialects.base import SQLDialect


class MySQLDialect(SQLDialect):
    name = "mysql"

    def quote_ident(self, ident: str) -> str:
        escaped = ident.replace("`", "``")
        return f"`{escaped}`"

    def limit_offset(self, limit: int, offset: int) -> str:
        return f"LIMIT {offset}, {limit}"

    def hash_expr(self, key_sql: str, buckets: int) -> str:
        # Use MOD(...) instead of % to avoid driver formatting issues.
        return f"MOD(CRC32(COALESCE(CAST({key_sql} AS CHAR), '__NULL__')), {buckets})"

    def string_prefix_expr(self, col_expr: str, length: int, lower: bool) -> str:
        expr = f"SUBSTRING({col_expr}, 1, {length})"
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
        # Window functions need MySQL 8.0 / MariaDB 10.2; older servers fail the statement and
        # the planner falls back to one boundary_query per boundary.
        return self.row_number_boundaries_query(relation_sql, key_sql, page_size)
