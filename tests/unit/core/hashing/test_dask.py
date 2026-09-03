import dask.dataframe as dd
import pandas as pd

from core.hashing._dask import _get_dask_hash, _get_series_hash


def test_dask_schema_hash_ignores_data(simple_df):
    df_a = simple_df.copy()
    df_b = simple_df.copy()
    df_b["age"] = df_b["age"] + 100

    ddf_a = dd.from_pandas(df_a, npartitions=2)
    ddf_b = dd.from_pandas(df_b, npartitions=2)

    assert _get_dask_hash(ddf_a, deep=False) == _get_dask_hash(ddf_b, deep=False)


def test_dask_deep_hash_changes_with_data(simple_df):
    df_a = simple_df.copy()
    df_b = simple_df.copy()
    df_b.loc[0, "name"] = "Zed"

    ddf_a = dd.from_pandas(df_a, npartitions=2)
    ddf_b = dd.from_pandas(df_b, npartitions=2)

    assert _get_dask_hash(ddf_a, deep=True) != _get_dask_hash(ddf_b, deep=True)


def test_dask_deep_hash_changes_with_partitioning(simple_df):
    ddf_two = dd.from_pandas(simple_df, npartitions=2)
    ddf_one = dd.from_pandas(simple_df, npartitions=1)

    assert _get_dask_hash(ddf_two, deep=True) != _get_dask_hash(ddf_one, deep=True)


def test_dask_series_hash_changes_with_name_and_partitions(simple_df):
    ddf = dd.from_pandas(simple_df, npartitions=2)
    series = ddf["age"]

    hash_a = _get_series_hash(series)

    renamed = series.rename("age_v2")
    hash_b = _get_series_hash(renamed)

    repartitioned = series.repartition(npartitions=1)
    hash_c = _get_series_hash(repartitioned)

    assert hash_a != hash_b
    assert hash_a != hash_c


def test_dask_series_hash_stable_on_same_series(simple_df):
    ddf = dd.from_pandas(simple_df, npartitions=2)
    series = ddf["age"]

    assert _get_series_hash(series) == _get_series_hash(series)
