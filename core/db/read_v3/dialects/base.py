from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Any, Sequence, Optional

from core.db.read_v3.models import ValueKind


class SQLDialect(ABC):
    name: str

    @abstractmethod
    def quote_ident(self, ident: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def limit_offset(self, limit: int, offset: int) -> str:
        raise NotImplementedError

    @abstractmethod
    def hash_expr(self, key_sql: str, buckets: int) -> str:
        raise NotImplementedError

    def quote_result_column(self, ident: str) -> str:
        return self.quote_ident(ident)

    def normalize_reflected_identifier(self, ident: str) -> str:
        """Return the raw identifier represented by dialect reflection metadata."""
        return ident

    def requires_string_output_cast(self, type_repr: str) -> bool:
        return False

    def stringify_output_expr(self, source_sql: str, *, type_repr: str) -> str:
        return source_sql

    def output_select_expr(self, source_sql: str, *, output_name: str, type_repr: str) -> str:
        expr = self.stringify_output_expr(source_sql, type_repr=type_repr)
        if expr == source_sql:
            return source_sql
        return f"{expr} AS {self.quote_ident(output_name)}"

    def string_prefix_expr(self, col_expr: str, length: int, lower: bool) -> str:
        raise NotImplementedError("string prefix expression not supported by this dialect")

    def quantile_expr(self, col_expr: str, quantile: float) -> str:
        raise NotImplementedError("quantile expression not supported by this dialect")

    def full_table_name(self, table: str, schema: Optional[str]) -> str:
        if schema:
            return f"{self.quote_ident(schema)}.{self.quote_ident(table)}"
        return self.quote_ident(table)

    def render_literal(self, value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, datetime):
            return f"'{value.strftime('%Y-%m-%d %H:%M:%S.%f')}'"
        if isinstance(value, date):
            return f"'{value.isoformat()}'"
        if isinstance(value, (int, float)):
            return str(value)
        escaped = str(value).replace("'", "''")
        return f"'{escaped}'"

    def detect_value_kind(self, type_repr: str) -> ValueKind:
        raw = (type_repr or "").lower().strip()
        for wrapper in ("nullable", "lowcardinality"):
            prefix = f"{wrapper}("
            while raw.startswith(prefix) and raw.endswith(")"):
                raw = raw[len(prefix) : -1].strip()
        if raw in {"json", "jsonb"}:
            return ValueKind.JSON
        if "uuid" in raw or "uniqueidentifier" in raw:
            return ValueKind.UUID
        if "bool" in raw or "bit" == raw:
            return ValueKind.BOOL
        if "timestamp" in raw or "datetime" in raw:
            return ValueKind.DATETIME
        if raw.startswith("date") or (" date" in raw and "time" not in raw):
            return ValueKind.DATE
        if any(token in raw for token in ("int", "decimal", "numeric", "number", "float", "double", "real")):
            return ValueKind.NUMERIC
        if any(
            token in raw
            for token in ("char", "text", "string", "clob", "nchar", "nvarchar", "binary", "varbinary")
        ):
            return ValueKind.STRING
        return ValueKind.UNKNOWN

    def boundary_query(self, relation_sql: str, key_sql: str, offset: int) -> str:
        return (
            f"SELECT {key_sql} AS boundary_value {relation_sql} "
            f"WHERE {key_sql} IS NOT NULL "
            f"ORDER BY {key_sql} ASC {self.limit_offset(1, offset)}"
        )

    def min_max_query(self, relation_sql: str, key_sql: str) -> str:
        return (
            f"SELECT MIN({key_sql}) AS min_v, MAX({key_sql}) AS max_v, "
            f"COUNT(*) AS total_rows, COUNT({key_sql}) AS non_null_rows {relation_sql}"
        )

    def null_count_query(self, relation_sql: str, key_sql: str) -> str:
        return f"SELECT COUNT(*) AS null_rows {relation_sql} WHERE {key_sql} IS NULL"

    def hash_predicate(self, key_sql: str, buckets: int, start_bucket: int, end_bucket: int) -> str:
        # [start_bucket, end_bucket)
        hash_sql = self.hash_expr(key_sql, buckets)
        if end_bucket == start_bucket + 1:
            return f"{hash_sql} = {start_bucket}"
        return f"{hash_sql} >= {start_bucket} AND {hash_sql} < {end_bucket}"

    def render_in_list(self, values: Sequence[Any]) -> str:
        return ", ".join(self.render_literal(value) for value in values)

    def cap_rows_sql(self, sql: str, row_cap: int) -> str:
        if row_cap <= 0:
            raise ValueError("row_cap must be positive")
        return f"SELECT * FROM ({sql}) __dvt_cap {self.limit_offset(row_cap, 0)}"

    def quoted_or_plain_ident(self, ident: str) -> str:
        return self.quote_ident(ident)
