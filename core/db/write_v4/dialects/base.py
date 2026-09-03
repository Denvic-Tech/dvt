from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class WriteDialect(ABC):
    name: str
    supports_schema: bool = True

    @abstractmethod
    def quote_ident(self, ident: str) -> str:
        raise NotImplementedError

    def full_table_name(self, table_name: str, schema_name: Optional[str]) -> str:
        if schema_name and self.supports_schema:
            return f"{self.quote_ident(schema_name)}.{self.quote_ident(table_name)}"
        return self.quote_ident(table_name)

    def full_column_name(self, table_name: str, schema_name: Optional[str], column_name: str) -> str:
        return f"{self.full_table_name(table_name, schema_name)}.{self.quote_ident(column_name)}"

    def null_safe_eq(self, left_sql: str, right_sql: str) -> str:
        return f"(({left_sql} = {right_sql}) OR ({left_sql} IS NULL AND {right_sql} IS NULL))"

    def delete_using_staging_sql(
        self,
        *,
        target_table: str,
        target_schema: Optional[str],
        staging_table: str,
        staging_schema: Optional[str],
        key_column: str,
    ) -> str:
        target_full = self.full_table_name(target_table, target_schema)
        staging_full = self.full_table_name(staging_table, staging_schema)
        target_key = self.full_column_name(target_table, target_schema, key_column)
        staging_key = f"s.{self.quote_ident(key_column)}"
        predicate = self.null_safe_eq(target_key, staging_key)
        return (
            f"DELETE FROM {target_full} "
            f"WHERE EXISTS (SELECT 1 FROM {staging_full} s WHERE {predicate})"
        )

    def truncate_sql(self, table_name: str, schema_name: Optional[str]) -> str:
        return f"TRUNCATE TABLE {self.full_table_name(table_name, schema_name)}"


class PostgresWriteDialect(WriteDialect):
    name = "postgresql"

    def quote_ident(self, ident: str) -> str:
        escaped = ident.replace('"', '""')
        return f'"{escaped}"'


class SqliteWriteDialect(PostgresWriteDialect):
    name = "sqlite"
    supports_schema = False

    def truncate_sql(self, table_name: str, schema_name: Optional[str]) -> str:
        return f"DELETE FROM {self.full_table_name(table_name, schema_name)}"


class OracleWriteDialect(PostgresWriteDialect):
    name = "oracle"


class MySQLWriteDialect(WriteDialect):
    name = "mysql"
    supports_schema = False

    def quote_ident(self, ident: str) -> str:
        escaped = ident.replace("`", "``")
        return f"`{escaped}`"


class MariaDBWriteDialect(MySQLWriteDialect):
    name = "mariadb"


class MssqlWriteDialect(WriteDialect):
    name = "mssql"

    def quote_ident(self, ident: str) -> str:
        escaped = ident.replace("]", "]]")
        return f"[{escaped}]"


class ClickHouseWriteDialect(MySQLWriteDialect):
    name = "clickhouse"
