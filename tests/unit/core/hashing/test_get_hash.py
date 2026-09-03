import pandas as pd
import pytest
from pydantic import BaseModel

from core.hashing.get_hash import get_hash


class SampleModel(BaseModel):
    value: int


class SampleModelAlt(BaseModel):
    value: int


def test_get_hash_string_and_none_equivalence():
    assert get_hash("alpha") == get_hash("alpha")
    assert get_hash("alpha") != get_hash("beta")

    # None is normalized to string inside get_hash
    assert get_hash(None) == get_hash("None")


def test_get_hash_ellipsis_normalization():
    assert get_hash(Ellipsis) == get_hash("Ellipsis")


def test_get_hash_list_order_sensitive():
    assert get_hash([1, 2, 3]) != get_hash([3, 2, 1])


def test_get_hash_dict_order_independent():
    payload_a = {"a": 1, "b": 2}
    payload_b = {"b": 2, "a": 1}

    assert get_hash(payload_a) == get_hash(payload_b)


def test_get_hash_pydantic_instance_and_class_differ():
    instance = SampleModel(value=10)

    assert get_hash(instance) == get_hash(instance)
    assert get_hash(SampleModel) == get_hash(SampleModel)
    assert get_hash(instance) != get_hash(SampleModel)


def test_get_hash_pydantic_class_distinguishes_types():
    assert get_hash(SampleModel) != get_hash(SampleModelAlt)


def test_get_hash_pandas_schema_vs_deep(simple_df):
    df_a = simple_df.copy()
    df_b = simple_df.copy()
    df_b["age"] = df_b["age"] + 100

    assert get_hash(df_a, deep=False) == get_hash(df_b, deep=False)
    assert get_hash(df_a, deep=True) != get_hash(df_b, deep=True)


def test_get_hash_empty_dataframe_deep_falls_back_to_schema():
    df = pd.DataFrame({"a": pd.Series([], dtype="int64")})

    assert get_hash(df, deep=False) == get_hash(df, deep=True)


def test_get_hash_unsupported_object_raises():
    class Custom:
        pass

    with pytest.raises(TypeError):
        get_hash(Custom())
