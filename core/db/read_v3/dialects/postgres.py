from core.db.read_v3.dialects.base import SQLDialect


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
