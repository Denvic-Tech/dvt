import numpy as np
import pandas as pd
import sqlalchemy as sa

from core.mapper.sa2pd_types import dtype_from_sqla_type


def test_dtype_from_sqla_type_integers_nullable():
    dtype, is_tz, is_naive = dtype_from_sqla_type(
        sa.Integer(), nullable=True, dialect_name="sqlite"
    )

    assert isinstance(dtype, pd.Int32Dtype)
    assert is_tz is False
    assert is_naive is False


def test_dtype_from_sqla_type_integers_non_nullable():
    dtype, _, _ = dtype_from_sqla_type(
        sa.BigInteger(), nullable=False, dialect_name="sqlite"
    )

    assert dtype == np.int64


def test_dtype_from_sqla_type_boolean_always_pandas_bool():
    dtype, _, _ = dtype_from_sqla_type(
        sa.Boolean(), nullable=False, dialect_name="sqlite"
    )

    assert isinstance(dtype, pd.BooleanDtype)


def test_dtype_from_sqla_type_datetime_tz():
    dtype, is_tz, is_naive = dtype_from_sqla_type(
        sa.DateTime(timezone=True), nullable=False, dialect_name="postgresql"
    )

    assert isinstance(dtype, pd.DatetimeTZDtype)
    assert is_tz is True
    assert is_naive is False


def test_dtype_from_sqla_type_numeric_as_object():
    dtype, _, _ = dtype_from_sqla_type(
        sa.Numeric(), nullable=False, dialect_name="sqlite", decimal_as_float=False
    )

    assert dtype is object
