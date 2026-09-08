from decimal import Decimal
from datetime import datetime, UTC

import numpy as np
import pandas as pd


def types_testing_dataframe(n_rows: int = 1000) -> pd.DataFrame:
    # базовые векторы
    idx = np.arange(n_rows)

    start_date = datetime.now(tz=UTC).date() - pd.Timedelta(seconds=n_rows)

    # дата с пропусками: берём валидный date_range и зануляем каждый второй
    dt_with_null = pd.date_range(start_date, periods=n_rows, freq='s').to_series()
    dt_with_null.iloc[::2] = pd.NaT
    dt_with_null = dt_with_null.to_numpy()

    df = pd.DataFrame({
        'int_col': idx,
        'float_col': np.linspace(0, 1, n_rows),
        'bool_col': (idx % 2 == 0),
        'only_false': [False for _ in range(n_rows)],
        'str_col': [f'str{i}' for i in range(n_rows)],
        'cat_col': pd.Categorical([f'cat{i % 3}' for i in range(n_rows)]),
        'string_col': pd.Series([f'str{i}' if i % 2 == 0 else None for i in range(n_rows)], dtype='string'),
        'datetime_col': pd.date_range(start_date, periods=n_rows, freq='s'),
        'datetime_tz_utc': pd.date_range(start_date, periods=n_rows, freq='s', tz='UTC'),
        'datetime_tz_helsinki': pd.date_range(start_date, periods=n_rows, freq='s', tz='Europe/Helsinki'),
        'timedelta_col': pd.to_timedelta(idx, unit='SECONDS'),
        'object_col': [{'i': int(i)} for i in idx],
        'int_with_null': pd.array([int(i) if i % 2 == 0 else None for i in idx], dtype='Int64'),
        'float_with_null': [float(i) if i % 2 == 0 else np.nan for i in idx],
        'bool_with_null': pd.array([True if i % 2 == 0 else None for i in idx], dtype='boolean'),
        'datetime_with_null': dt_with_null,  # <- фикс
        'category_with_null': pd.Categorical([f'c{i % 3}' if i % 2 == 0 else None for i in idx]),
        'period_col': pd.period_range(start_date, periods=n_rows, freq='s'),
        'interval_col': pd.IntervalIndex.from_breaks(np.arange(n_rows + 1)),
        # 'complex_col': np.array([complex(i, -i) for i in idx]),  # TODO: ADD complex types support
        'decimal_col': [Decimal(i) / Decimal(10) for i in range(n_rows)],
        'bytes_col': [bytes(f'byte{i}', 'utf-8') for i in idx],
    })
    return df


def types_testing_dataframe_with_index(n_rows: int = 1000) -> pd.DataFrame:
    df = types_testing_dataframe(n_rows)
    df = df.set_index(["int_col"])
    return df


def types_testing_dataframe_with_multiindex(n_rows: int = 1000) -> pd.DataFrame:
    df = types_testing_dataframe(n_rows)
    df = df.set_index(["int_col", "float_col"])
    return df


def types_testing_dataframe_with_string_index(n_rows: int = 1000) -> pd.DataFrame:
    df = types_testing_dataframe(n_rows)
    df = df.set_index(["int_col", "string_col"])
    return df
