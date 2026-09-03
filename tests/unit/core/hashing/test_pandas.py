import pandas as pd
import pandas.testing as tm

from core.hashing._pandas import _get_pandas_hash


def test_schema_hash_changes_with_index_type(simple_df):
    df_range = simple_df.copy()
    df_range.index = pd.RangeIndex(start=0, stop=len(df_range))

    df_index = simple_df.copy()
    df_index.index = pd.Index(list(range(len(df_index))), name="idx")

    assert _get_pandas_hash(df_range, deep=False) != _get_pandas_hash(df_index, deep=False)


def test_schema_hash_changes_with_shape(simple_df):
    df_full = simple_df.copy()
    df_short = simple_df.head(3)

    assert _get_pandas_hash(df_full, deep=False) != _get_pandas_hash(df_short, deep=False)


def test_deep_hash_changes_with_data(simple_df):
    df_a = simple_df.copy()
    df_b = simple_df.copy()
    df_b.loc[0, "name"] = "Zed"

    assert _get_pandas_hash(df_a, deep=True) != _get_pandas_hash(df_b, deep=True)


def test_deep_hash_preserves_schema_and_data(simple_df):
    df_a = simple_df.copy()
    df_b = simple_df.copy()

    assert _get_pandas_hash(df_a, deep=True) == _get_pandas_hash(df_b, deep=True)
    tm.assert_frame_equal(df_a, df_b)
