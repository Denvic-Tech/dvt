import re
from typing import Any

from functools import lru_cache

from loguru import logger

import sqlalchemy as sa
from sqlalchemy.sql import sqltypes
from clickhouse_sqlalchemy.drivers.base import ClickHouseDialect

from sqlalchemy.dialects.postgresql.base import ischema_names as postgresql_ischema_names
from sqlalchemy.dialects.mysql.base import ischema_names as mysql_ischema_names
from sqlalchemy.dialects.mssql.base import ischema_names as mssql_ischema_names
from sqlalchemy.dialects.sqlite.base import ischema_names as sqlite_ischema_names
from sqlalchemy.dialects.oracle.base import ischema_names as oracle_ischema_names
from clickhouse_sqlalchemy.drivers.base import ischema_names as clickhouse_ischema_names


oracle_remove_size = re.compile(r"\(\S+\)")


def get_ischema_names(dialect: sa.Dialect) -> dict[str, sqltypes.TypeEngine[Any]]:
    """
    Get the ischema_names for the given SQLAlchemy engine.
    """
    if dialect.name == "postgresql":
        return postgresql_ischema_names
    elif dialect.name == "mysql":
        return mysql_ischema_names
    elif dialect.name == "mssql":
        return mssql_ischema_names
    elif dialect.name == "sqlite":
        return sqlite_ischema_names
    elif dialect.name == "oracle":
        return oracle_ischema_names
    elif dialect.name == "clickhouse":
        return clickhouse_ischema_names
    else:
        raise ValueError(f"Unsupported database dialect: {dialect.name}")


@lru_cache(maxsize=1)
def pg_dialect():
    return sa.dialects.postgresql.base.PGDialect()


@lru_cache(maxsize=1)
def sqlite_dialect():
    return sa.dialects.sqlite.base.SQLiteDialect()


@lru_cache(maxsize=1)
def ch_dialect():
    return ClickHouseDialect()


def get_pg_sa_type(sql_type: str, **kwargs) -> sqltypes.TypeEngine[Any]:
    """
    Get the SQLAlchemy type for the given PostgreSQL SQL type.
    """
    enum_values: str | None = kwargs.get("enum_values", None)
    udt_name: str | None = kwargs.get("udt_name", None)
    if sql_type == "USER-DEFINED":
        if enum_values:
            return sqltypes.Enum(*enum_values.split(','))
        else:
            return sqltypes.NullType()
    if sql_type == "ARRAY":
        base_name = None
        if udt_name:
            base_name = udt_name[1:] if udt_name.startswith("_") else udt_name
        base_type_factory = postgresql_ischema_names.get(base_name or "")
        try:
            base_type = base_type_factory() if base_type_factory else sqltypes.Text()
        except Exception:
            base_type = sqltypes.Text()
        return sa.dialects.postgresql.ARRAY(base_type)

    dialect = pg_dialect()
    return dialect._reflect_type(
        format_type=sql_type,
        domains={},
        enums={},
        type_description=f"PostgreSQL '{sql_type}' Type",
    )


def get_sqlite_sa_type(sql_type: str, **kwargs) -> sqltypes.TypeEngine[Any]:
    """
    Get the SQLAlchemy type for the given SQLite SQL type.
    """
    dialect = sqlite_dialect()
    return dialect._resolve_type_affinity(sql_type)


def get_mysql_sa_type(sql_type: str, **kwargs) -> sqltypes.TypeEngine[Any]:
    """
    Get the SQLAlchemy type for the given MySQL SQL type.
    """
    enum_values: str | None = kwargs.get("enum_values", None)
    if sql_type == "enum" and enum_values:
        return sqltypes.Enum(*enum_values.split(','))

    sa_type = mysql_ischema_names.get(sql_type, None)
    if sa_type is None:
        raise ValueError(f"Unsupported MySQL type: {sql_type}")
    return sa_type()


def get_mssql_sa_type(sql_type: str, **kwargs) -> sqltypes.TypeEngine[Any]:
    """
    Get the SQLAlchemy type for the given MSSQL SQL type.
    """
    sa_type = mssql_ischema_names.get(sql_type, None)
    if sa_type is None:
        raise ValueError(f"Unsupported MSSQL type: {sql_type}")
    return sa_type()


def get_oracle_sa_type(sql_type: str, **kwargs) -> sqltypes.TypeEngine[Any]:
    """
    Get the SQLAlchemy type for the given Oracle SQL type.
    """
    # copied from sqlalchemy/dialects/oracle/base.py:OracleDialect.get_multi_columns

    if sql_type in oracle_ischema_names:
        return oracle_ischema_names[sql_type]()
    elif "WITH TIME ZONE" in sql_type:
        return sqltypes.TIMESTAMP(timezone=True)
    elif "WITH LOCAL TIME ZONE" in sql_type:
        return sqltypes.TIMESTAMP(timezone=True)
    elif "NUMBER(1,0)" in sql_type:
        return sqltypes.BOOLEAN()
    elif "NUMBER" in sql_type:
        match = re.match(r'NUMBER\((\d+),\s*0\)', sql_type)
        if match:
            precision = int(match.group(1))
            if precision <= 10:
                return sqltypes.INTEGER()
            elif precision <= 19:
                return sqltypes.BIGINT()
            else:
                return sqltypes.BIGINT()

        # NUMBER(p,s) → NUMERIC
        match = re.match(r'NUMBER\((\d+),\s*(\d+)\)', sql_type)
        if match:
            precision = int(match.group(1))
            scale = int(match.group(2))
            return sqltypes.NUMERIC(precision=precision, scale=scale)

        # NUMBER без параметров → FLOAT
        if sql_type == "NUMBER":
            return sqltypes.FLOAT()

        sql_type = re.sub(oracle_remove_size, "", sql_type)
        try:
            return oracle_ischema_names[sql_type]()
        except KeyError:
            logger.warning(
                f"Did not recognize type '{sql_type}' in Oracle dialect."
            )
            return sqltypes.NULLTYPE
        except Exception as e:
            logger.error(f"Error getting Oracle type for '{sql_type}': {e}")
            raise ValueError(f"Unsupported Oracle type: {sql_type}") from e

    else:
        sql_type = re.sub(oracle_remove_size, "", sql_type)
        try:
            return oracle_ischema_names[sql_type]()
        except KeyError:
            logger.warning(
                f"Did not recognize type '{sql_type}' in Oracle dialect."
            )
            return sqltypes.NULLTYPE
        except Exception as e:
            logger.error(f"Error getting Oracle type for '{sql_type}': {e}")
            raise ValueError(f"Unsupported Oracle type: {sql_type}") from e


def get_ch_sa_type(sql_type: str, **kwargs) -> sqltypes.TypeEngine[Any]:
    """
    Get the SQLAlchemy type for the given ClickHouse SQL type.
    """
    dialect = ch_dialect()
    sa_type = dialect._get_column_type(
        name='temp_column',
        spec=sql_type
    )

    while hasattr(sa_type, 'nested_type'):
        sa_type = sa_type.nested_type

    return _normalize_ch_sa_type(sa_type, sql_type)


def _normalize_ch_sa_type(
    sa_type: Any,
    sql_type: str,
) -> sqltypes.TypeEngine[Any]:
    """
    clickhouse_sqlalchemy may return a type class, an already-created instance,
    or a factory (for example Enum lambdas). Normalize them to a TypeEngine instance.
    """
    if isinstance(sa_type, sqltypes.TypeEngine):
        return sa_type

    if isinstance(sa_type, type) and issubclass(sa_type, sqltypes.TypeEngine):
        return sa_type()

    if callable(sa_type):
        normalized = sa_type()
        if isinstance(normalized, sqltypes.TypeEngine):
            return normalized
        raise TypeError(
            f"ClickHouse type factory for '{sql_type}' returned unsupported value: "
            f"{type(normalized).__name__}"
        )

    raise TypeError(
        f"Unsupported ClickHouse SQLAlchemy type for '{sql_type}': "
        f"{type(sa_type).__name__}"
    )
