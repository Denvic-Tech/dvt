import pandas as pd
import pytest

from core.utils._pandas import (
    get_meta_df,
    get_useful_indexes,
    is_default_range_index,
    iter_index_levels,
    normalize_index_for_db_write,
)


class _DaskLike:
    def __init__(self, meta: pd.DataFrame) -> None:
        self._meta = meta


def test_get_meta_df_returns_head_for_pandas_dataframe():
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]}).set_index("a")

    meta = get_meta_df(df)

    assert isinstance(meta, pd.DataFrame)
    assert meta.index.name == "a"
    assert meta.empty is True
    assert list(meta.columns) == ["b"]


def test_get_meta_df_returns_meta_for_dask_like():
    meta = pd.DataFrame({"a": [], "b": []}).set_index("a")
    dask_like = _DaskLike(meta)

    assert get_meta_df(dask_like) is meta


def test_is_default_range_index_true_for_default_range():
    df = pd.DataFrame({"a": [1, 2]})

    assert is_default_range_index(df) is True


def test_is_default_range_index_false_for_named_range_index():
    df = pd.DataFrame({"a": [1, 2]}).set_index(pd.RangeIndex(0, 2, name="idx"))

    assert is_default_range_index(df) is False


def test_iter_index_levels_skips_default_range_index():
    df = pd.DataFrame({"a": [1, 2]})

    assert list(iter_index_levels(df)) == []


def test_iter_index_levels_returns_named_index():
    df = pd.DataFrame({"a": [1, 2]}).set_index("a")

    result = list(iter_index_levels(df))

    assert result == [("a", df.index.dtype)]


def test_iter_index_levels_multiindex_skips_unnamed_levels():
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"], "c": [10, 20]}).set_index(["a", "b"])
    df.index = pd.MultiIndex.from_arrays([df.index.get_level_values(0), df.index.get_level_values(1)],
                                          names=["a", None])

    result = list(iter_index_levels(df))

    assert len(result) == 1
    assert result[0][0] == "a"


def test_get_useful_indexes_collects_names():
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]}).set_index(["a", "b"])

    assert get_useful_indexes(df) == ["a", "b"]


def test_get_useful_indexes_skips_internal_dvt_index():
    df = pd.DataFrame({"value": [1, 2]})
    df.index = pd.Index([0, 1], dtype="int64", name="__dvt_partition_bucket")

    assert get_useful_indexes(df) == []


def test_normalize_index_for_db_write_drops_internal_index_without_materializing_it():
    df = pd.DataFrame({"value": [10, 20]})
    df.index = pd.Index([1, 2], name="__dvt_partition_key")

    result = normalize_index_for_db_write(df)

    assert list(result.columns) == ["value"]
    assert result["value"].tolist() == [10, 20]


def test_normalize_index_for_db_write_uses_ordinary_column_on_name_collision():
    df = pd.DataFrame({"id": [1, 2], "value": [10, 20]})
    df.index = pd.Index([1, 2], name="id")

    result = normalize_index_for_db_write(df)

    assert list(result.columns) == ["id", "value"]
    assert result.to_dict(orient="records") == [
        {"id": 1, "value": 10},
        {"id": 2, "value": 20},
    ]


def test_normalize_index_for_db_write_materializes_genuine_index_only_field():
    df = pd.DataFrame({"value": [10, 20]}, index=pd.Index([1, 2], name="id"))

    result = normalize_index_for_db_write(df)

    assert list(result.columns) == ["id", "value"]
    assert result.to_dict(orient="records") == [
        {"id": 1, "value": 10},
        {"id": 2, "value": 20},
    ]
