"""DataFrame metadata and type-conversion facade."""

from typing import Any

from core.mapper.sa2pd_types import dtype_from_sqla_type as _dtype_from_sqla_type
from core.mapper.sql2sa_types import get_ch_sa_type as _get_ch_sa_type
from core.metadata import get_df_metadata
from core.types import Column, DataFrameMetadata, DataType


def sqlalchemy_type_to_pandas_dtype(
    col_type: Any,
    *,
    nullable: bool,
    dialect_name: str,
    tz_for_timestamptz: str = "UTC",
    decimal_as_float: bool = True,
    use_string_dtype: bool = True,
    enum_as_category: bool = False,
):
    """Map a SQLAlchemy type to the pandas dtype tuple used by DVT."""
    return _dtype_from_sqla_type(
        col_type,
        nullable=nullable,
        dialect_name=dialect_name,
        tz_for_timestamptz=tz_for_timestamptz,
        decimal_as_float=decimal_as_float,
        use_string_dtype=use_string_dtype,
        enum_as_category=enum_as_category,
    )


def clickhouse_type_to_sqlalchemy(sql_type: str, **kwargs):
    """Resolve a ClickHouse type string to a SQLAlchemy type."""
    return _get_ch_sa_type(sql_type, **kwargs)


# Compatibility-friendly public names for straightforward migration of existing
# extensions. These are wrappers, not imports of the internal mapper modules.
dtype_from_sqla_type = sqlalchemy_type_to_pandas_dtype
get_ch_sa_type = clickhouse_type_to_sqlalchemy

__all__ = [
    "Column",
    "DataFrameMetadata",
    "DataType",
    "clickhouse_type_to_sqlalchemy",
    "dtype_from_sqla_type",
    "get_ch_sa_type",
    "get_df_metadata",
    "sqlalchemy_type_to_pandas_dtype",
]
