from core.db.read_v3.dialects.base import SQLDialect


class SqliteDialect(SQLDialect):
    name = "sqlite"

    def quote_ident(self, ident: str) -> str:
        escaped = ident.replace('"', '""')
        return f'"{escaped}"'

    def limit_offset(self, limit: int, offset: int) -> str:
        return f"LIMIT {limit} OFFSET {offset}"

    def hash_expr(self, key_sql: str, buckets: int) -> str:
        # SQLite has no built-in stable hash for generic SQL values;
        # use a deterministic text-length based expression for bucketization.
        return (
            f"(abs(length(coalesce(cast({key_sql} as text), '__NULL__')) * 1315423911) % {buckets})"
        )

    def string_prefix_expr(self, col_expr: str, length: int, lower: bool) -> str:
        expr = f"substr({col_expr}, 1, {length})"
        return f"lower({expr})" if lower else expr
