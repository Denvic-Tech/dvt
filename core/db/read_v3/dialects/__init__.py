from sqlalchemy.engine import Engine

from core.db.read_v3.dialects.base import SQLDialect
from core.db.read_v3.dialects.clickhouse import ClickHouseDialect
from core.db.read_v3.dialects.mssql import MssqlDialect
from core.db.read_v3.dialects.mysql import MySQLDialect
from core.db.read_v3.dialects.oracle import OracleDialect
from core.db.read_v3.dialects.postgres import PostgresDialect
from core.db.read_v3.dialects.sqlite import SqliteDialect
from core.db.read_v3.errors import ReadV3DialectError


def resolve_dialect(engine: Engine) -> SQLDialect:
    name = (engine.dialect.name or "").lower()
    if "clickhouse" in name:
        return ClickHouseDialect()
    if "postgres" in name:
        return PostgresDialect()
    if "mysql" in name or "mariadb" in name:
        return MySQLDialect()
    if "mssql" in name or "sqlserver" in name:
        return MssqlDialect()
    if "oracle" in name:
        return OracleDialect()
    if "sqlite" in name:
        return SqliteDialect()
    raise ReadV3DialectError(f"Unsupported SQL dialect for read_v3: {engine.dialect.name!r}")


__all__ = [
    "SQLDialect",
    "PostgresDialect",
    "MySQLDialect",
    "MssqlDialect",
    "OracleDialect",
    "ClickHouseDialect",
    "SqliteDialect",
    "resolve_dialect",
]
