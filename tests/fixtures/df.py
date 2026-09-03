import pytest

from decimal import Decimal

import pandas as pd
import numpy as np
import dask.dataframe as dd


@pytest.fixture(scope="session")
def simple_df() -> pd.DataFrame:
    """Простая фикстура Pandas DataFrame для тестов."""
    return pd.DataFrame({
        'id': [1, 2, 3, 4, 5],
        'name': ['Alice', 'Bob', 'Charlie', 'Dave', 'Eve'],
        'age': [25, 30, 35, 40, 45],
        'unused_column': ['x', 'y', 'z', 'a', 'b']
    })

@pytest.fixture(scope="session")
def simple_df_two() -> pd.DataFrame:
    """Простая фикстура Pandas DataFrame для тестов."""
    return pd.DataFrame({
        'name': ['Alice', 'Bob', 'Charlie', 'Dave', 'Eve'],
        'surname': ['Smith', 'Johnson', 'Williams', 'Brown', 'Davis'],
    })


@pytest.fixture(scope="session")
def simple_ddf(simple_df: pd.DataFrame) -> dd.DataFrame:
    """Простая фикстура Dask DataFrame для тестов."""
    return dd.from_pandas(simple_df, npartitions=2)


@pytest.fixture(scope="session")
def types_test_dataframe() -> pd.DataFrame:
    """Фикстура для генерации DataFrame с разнообразными типами данных."""
    n = 6
    df = pd.DataFrame({
        'int_col': np.arange(n, dtype=int),
        'float_col': np.linspace(0, 1, n),
        'bool_col': [True, False] * (n // 2) + [True] * (n % 2),
        'str_col': [f'str{i}' for i in range(n)],
        'cat_col': pd.Categorical([f'cat{i % 3}' for i in range(n)]),
        'string_col': pd.Series([f'str{i}' if i % 2 == 0 else None for i in range(n)], dtype='string'),
        'datetime_col': pd.date_range('2021-01-01', periods=n, freq='D'),
        'datetime_tz_utc': pd.date_range('2021-01-01', periods=n, freq='D', tz='UTC'),
        'datetime_tz_helsinki': pd.date_range('2021-01-01', periods=n, freq='h', tz='Europe/Helsinki'),
        'timedelta_col': pd.to_timedelta(np.arange(n), unit='D'),
        'object_col': [{'i': i} for i in range(n)],
        'int_with_null': pd.array([i if i % 2 == 0 else None for i in range(n)], dtype='Int64'),
        'float_with_null': [i if i % 2 == 0 else np.nan for i in range(n)],
        'bool_with_null': pd.array([True if i % 2 == 0 else None for i in range(n)], dtype='boolean'),
        'datetime_with_null': pd.to_datetime([None if i % 2 == 0 else f'2021-01-{i + 1:02d}' for i in range(n)]),
        'category_with_null': pd.Categorical([f'c{i % 3}' if i % 2 == 0 else None for i in range(n)]),
        'period_col': pd.period_range('2021-01', periods=n, freq='M'),
        'interval_col': pd.IntervalIndex.from_breaks(np.arange(n + 1)),
        'complex_col': np.array([complex(i, -i) for i in range(n)]),
        'decimal_col': [Decimal(i) / Decimal(10) for i in range(n)],
        'bytes_col': [bytes(f'byte{i}', 'utf-8') for i in range(n)],
        'mixed_obj_col': [i if i % 2 == 0 else str(i) for i in range(n)],
    })
    return df
