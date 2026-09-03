import warnings
from typing import Any

import sqlalchemy as sa
from clickhouse_sqlalchemy import types as clickhouse_types
from sqlalchemy.dialects import mssql
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.sql import sqltypes

from core.mapper.sa2py_types import get_py_type


class NoPyType(sqltypes.TypeEngine):
    @property
    def python_type(self):
        raise NotImplementedError


def test_get_py_type_custom_inet():
    assert get_py_type(INET()) is str


def test_get_py_type_json_and_binary():
    assert get_py_type(sa.JSON()) is dict
    assert get_py_type(sa.LargeBinary()) is object


def test_get_py_type_maps_mssql_uniqueidentifier_and_binary_to_str() -> None:
    assert get_py_type(mssql.UNIQUEIDENTIFIER()) is str
    assert get_py_type(mssql.BINARY(16)) is str
    assert get_py_type(mssql.VARBINARY(16)) is str


def test_get_py_type_impl_resolution():
    class IntDecorator(sa.TypeDecorator):
        impl = sa.Integer

    decorator = IntDecorator()

    assert get_py_type(decorator) is int


def test_get_py_type_normalizes_clickhouse_float_class_and_instance() -> None:
    assert get_py_type(clickhouse_types.Float64) is float
    assert get_py_type(clickhouse_types.Float64()) is float


def test_get_py_type_unwraps_clickhouse_nullable_type() -> None:
    assert get_py_type(clickhouse_types.Nullable(clickhouse_types.Float64)) is float
    assert get_py_type(clickhouse_types.Nullable(clickhouse_types.Int64)) is int


def test_get_py_type_unwraps_nested_clickhouse_low_cardinality_type() -> None:
    sql_type = clickhouse_types.LowCardinality(
        clickhouse_types.Nullable(clickhouse_types.Int64)
    )

    assert get_py_type(sql_type) is int


def test_get_py_type_warns_on_not_implemented():
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        result = get_py_type(NoPyType())

    assert result is Any
    assert any("does not have a defined python_type" in str(w.message) for w in captured)
