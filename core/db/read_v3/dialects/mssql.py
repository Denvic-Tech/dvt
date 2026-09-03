import re
from datetime import date, datetime, time

from core.db.read_v3.dialects.base import SQLDialect
from core.db.read_v3.models import ValueKind

_MSSQL_BINARY_TYPES = frozenset({"binary", "varbinary", "image", "rowversion", "timestamp"})
_MSSQL_STRING_TYPES = frozenset(
    {
        "time",
        "xml",
        "sql_variant",
        "hierarchyid",
        "geometry",
        "geography",
        "vector",
    }
)


class MssqlDialect(SQLDialect):
    name = "mssql"

    @staticmethod
    def _normalize_type_repr(type_repr: str) -> str:
        return (type_repr or "").strip().lower()

    @classmethod
    def _base_type_name(cls, type_repr: str) -> str:
        return cls._normalize_type_repr(type_repr).split("(", maxsplit=1)[0].strip()

    def quote_ident(self, ident: str) -> str:
        escaped = ident.replace("]", "]]")
        return f"[{escaped}]"

    def limit_offset(self, limit: int, offset: int) -> str:
        return f"OFFSET {offset} ROWS FETCH NEXT {limit} ROWS ONLY"

    def hash_expr(self, key_sql: str, buckets: int) -> str:
        return (
            f"(ABS(CHECKSUM(COALESCE(CAST({key_sql} AS NVARCHAR(MAX)), '__NULL__'))) % {buckets})"
        )

    def requires_string_output_cast(self, type_repr: str) -> bool:
        type_name = self._base_type_name(type_repr)
        return (
            type_name == "uniqueidentifier"
            or type_name in _MSSQL_BINARY_TYPES
            or type_name in _MSSQL_STRING_TYPES
        )

    def stringify_output_expr(self, source_sql: str, *, type_repr: str) -> str:
        type_name = self._base_type_name(type_repr)
        if type_name == "uniqueidentifier":
            result = f"CAST({source_sql} AS NVARCHAR(MAX))"
        elif type_name == "image":
            result = (
                f"CONVERT(VARCHAR(MAX), CONVERT(VARBINARY(MAX), {source_sql}), 2)"
            )
        elif type_name in {"rowversion", "timestamp"}:
            result = f"CONVERT(CHAR(16), {source_sql}, 2)"
        elif type_name in _MSSQL_BINARY_TYPES:
            result = f"CONVERT(VARCHAR(MAX), {source_sql}, 2)"
        elif type_name in {"hierarchyid", "geometry", "geography"}:
            result = f"{source_sql}.ToString()"
        elif type_name in _MSSQL_STRING_TYPES:
            result = f"CAST({source_sql} AS NVARCHAR(MAX))"
        else:
            result = source_sql
        return result

    def detect_value_kind(self, type_repr: str) -> ValueKind:
        type_name = self._base_type_name(type_repr)
        if type_name == "bit":
            return ValueKind.BOOL
        if type_name in {"money", "smallmoney"}:
            return ValueKind.NUMERIC
        if type_name in _MSSQL_BINARY_TYPES or type_name in _MSSQL_STRING_TYPES:
            return ValueKind.STRING
        return super().detect_value_kind(type_repr)

    def render_literal(self, value):
        if isinstance(value, datetime):
            literal = value.isoformat(timespec="microseconds")
            target_type = "DATETIMEOFFSET(6)" if value.utcoffset() is not None else "DATETIME2(6)"
            return f"CAST('{literal}' AS {target_type})"
        if isinstance(value, date):
            return f"CAST('{value.isoformat()}' AS DATE)"
        if isinstance(value, time):
            return f"CAST('{value.isoformat(timespec='microseconds')}' AS TIME(6))"
        if isinstance(value, bool):
            return "1" if value else "0"
        return super().render_literal(value)

    @staticmethod
    def _inject_top_into_cte_select(sql: str, row_cap: int) -> str | None:
        if not re.match(r"^\s*with\b", sql, flags=re.IGNORECASE):
            return None

        depth = 0
        idx = 0
        while idx < len(sql):
            char = sql[idx]
            if char == "(":
                depth += 1
                idx += 1
                continue
            if char == ")":
                depth = max(0, depth - 1)
                idx += 1
                continue

            if depth == 0:
                match = re.match(r"select\b", sql[idx:], flags=re.IGNORECASE)
                if match:
                    start = idx
                    end = idx + match.end()
                    tail = sql[end:]
                    if re.match(r"^\s+top\s*\(", tail, flags=re.IGNORECASE):
                        return sql
                    return f"{sql[:start]}SELECT TOP ({row_cap}){tail}"
            idx += 1
        return None

    def cap_rows_sql(self, sql: str, row_cap: int) -> str:
        if row_cap <= 0:
            raise ValueError("row_cap must be positive")
        normalized_sql = sql.strip().rstrip(";")

        cte_top_sql = self._inject_top_into_cte_select(normalized_sql, row_cap)
        if cte_top_sql is not None:
            return cte_top_sql

        # SQL Server forbids ORDER BY inside derived tables unless TOP/OFFSET/FOR XML is present.
        if re.search(r"\border\s+by\b", normalized_sql, flags=re.IGNORECASE) and not re.search(
            r"\boffset\b", normalized_sql, flags=re.IGNORECASE
        ):
            normalized_sql = f"{normalized_sql} OFFSET 0 ROWS"
        return f"SELECT TOP ({row_cap}) * FROM ({normalized_sql}) __dvt_cap"

    def string_prefix_expr(self, col_expr: str, length: int, lower: bool) -> str:
        expr = f"SUBSTRING({col_expr}, 1, {length})"
        return f"LOWER({expr})" if lower else expr
