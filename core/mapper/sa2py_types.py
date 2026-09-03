import warnings
from typing import Any

from sqlalchemy.dialects.postgresql.types import INET
from sqlalchemy.sql import sqltypes
from sqlalchemy.sql.type_api import to_instance

try:
    from sqlalchemy.dialects import mssql as mssql_dialect
except ImportError:
    mssql_dialect = None

try:
    from clickhouse_sqlalchemy import types as clickhouse_sqlalchemy_types
except ImportError:
    clickhouse_sqlalchemy_types = None


custom_types_map: dict[type[sqltypes.TypeEngine[Any]], type] = {
    INET: str,
}

if mssql_dialect is not None:
    custom_types_map.update(
        {
            mssql_dialect.UNIQUEIDENTIFIER: str,
            mssql_dialect.BINARY: str,
            mssql_dialect.VARBINARY: str,
        }
    )

if clickhouse_sqlalchemy_types is not None:
    custom_types_map.update(
        {
            clickhouse_sqlalchemy_types.IPv4: str,
            clickhouse_sqlalchemy_types.IPv6: str,
        }
    )


def get_py_type(
    sql_type: sqltypes.TypeEngine[Any] | type[sqltypes.TypeEngine[Any]],
):
    sql_type = to_instance(sql_type)

    if sql_type.__class__ in custom_types_map:
        return custom_types_map.get(sql_type.__class__)

    if isinstance(sql_type, sqltypes.JSON):
        return dict

    if isinstance(sql_type, sqltypes.LargeBinary):
        return object

    while hasattr(sql_type, "nested_type"):
        sql_type = to_instance(sql_type.nested_type)

    if hasattr(sql_type, "impl"):
        return get_py_type(sql_type.impl)
    try:
        return sql_type.python_type
    except NotImplementedError:
        warnings.warn(
            f"SQLAlchemy type {sql_type} does not have a defined python_type. Returning Any.",
            UserWarning,
            stacklevel=2,
        )
        return Any
