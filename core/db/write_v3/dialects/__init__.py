from sqlalchemy.engine import Engine

from core.db.write_v3.dialects.base import (
    ClickHouseWriteDialect,
    MariaDBWriteDialect,
    MssqlWriteDialect,
    MySQLWriteDialect,
    OracleWriteDialect,
    PostgresWriteDialect,
    SqliteWriteDialect,
    WriteDialect,
)
from core.db.write_v3.errors import WriteV3DialectError


def resolve_dialect(engine: Engine) -> WriteDialect:
    name = (engine.dialect.name or "").lower()
    if "clickhouse" in name:
        return ClickHouseWriteDialect()
    if "postgres" in name:
        return PostgresWriteDialect()
    if "mysql" in name:
        return MySQLWriteDialect()
    if "mariadb" in name:
        return MariaDBWriteDialect()
    if "mssql" in name or "sqlserver" in name:
        return MssqlWriteDialect()
    if "oracle" in name:
        return OracleWriteDialect()
    if "sqlite" in name:
        return SqliteWriteDialect()
    raise WriteV3DialectError(f"Unsupported SQL dialect for write_v3: {engine.dialect.name!r}")


__all__ = [
    "WriteDialect",
    "PostgresWriteDialect",
    "MySQLWriteDialect",
    "MariaDBWriteDialect",
    "MssqlWriteDialect",
    "OracleWriteDialect",
    "SqliteWriteDialect",
    "ClickHouseWriteDialect",
    "resolve_dialect",
]
