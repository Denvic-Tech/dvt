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
