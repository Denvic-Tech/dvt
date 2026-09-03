import numpy as np
import pandas as pd
import pytest

from core.utils.dtype_coercion import _coerce_to_bool, apply_dtypes_and_casts


def test_coerce_to_bool_returns_same_bool_series():
    series = pd.Series([True, False, pd.NA], dtype="boolean")

    result = _coerce_to_bool(series)

    assert result is series


def test_coerce_to_bool_converts_strings_and_numbers():
    series = pd.Series(["1", "0", "true", "false", "yes", "no", None, "maybe"])

    result = _coerce_to_bool(series)

    assert result.dtype == "boolean"
    assert result.tolist() == [True, False, True, False, True, False, pd.NA, pd.NA]


def test_apply_dtypes_handles_datetime_columns():
    df = pd.DataFrame({"ts": ["2024-01-01", "invalid"], "naive": ["2024-02-02", None]})

    dtype_map = {"ts": object, "naive": object}
    result = apply_dtypes_and_casts(df, dtype_map, tz_cols=["ts"], naive_dt_cols=["naive"])

    assert pd.api.types.is_datetime64_any_dtype(result["ts"].dtype)
    assert result["ts"].isna().tolist() == [False, True]
    assert pd.api.types.is_datetime64_any_dtype(result["naive"].dtype)
    assert result["naive"].isna().tolist() == [False, True]


def test_apply_dtypes_normalizes_datetime_precision_to_ns():
    ts_us = np.array(
        ["2026-02-18T09:53:06.070123", "2026-02-18T09:53:06.070124"],
        dtype="datetime64[us]",
    )
    df = pd.DataFrame({"ts": pd.Series(ts_us), "naive": pd.Series(ts_us)})

    result = apply_dtypes_and_casts(
        df,
        {"ts": object, "naive": object},
        tz_cols=["ts"],
        naive_dt_cols=["naive"],
    )

    assert str(result["ts"].dtype) == "datetime64[ns, UTC]"
    assert str(result["naive"].dtype) == "datetime64[ns]"


def test_apply_dtypes_handles_numeric_columns():
    df = pd.DataFrame({"int_col": ["1", "bad", "3"], "float_col": ["1.5", "bad", 2.5]})
    dtype_map = {"int_col": pd.Int64Dtype(), "float_col": pd.Float64Dtype()}

    result = apply_dtypes_and_casts(df, dtype_map, tz_cols=[], naive_dt_cols=[])

    assert pd.api.types.is_float_dtype(result["int_col"].dtype)
    assert result["int_col"].isna().tolist() == [False, True, False]
    assert pd.api.types.is_float_dtype(result["float_col"].dtype)
    assert result["float_col"].isna().tolist() == [False, True, False]


def test_apply_dtypes_handles_boolean_columns():
    df = pd.DataFrame({"flag": ["1", "0", "yes", "no", "maybe"]})
    dtype_map = {"flag": bool}

    result = apply_dtypes_and_casts(df, dtype_map, tz_cols=[], naive_dt_cols=[])

    assert result["flag"].dtype == "boolean"
    assert result["flag"].tolist() == [True, False, True, False, pd.NA]


def test_apply_dtypes_handles_string_columns():
    df = pd.DataFrame({"text": [1, 2, 3]})
    dtype_map = {"text": pd.StringDtype()}

    result = apply_dtypes_and_casts(df, dtype_map, tz_cols=[], naive_dt_cols=[])

    assert pd.api.types.is_string_dtype(result["text"].dtype)


def test_apply_dtypes_falls_back_to_object_on_error():
    df = pd.DataFrame({"bad": ["a", "b"]})

    class BrokenDtype:
        def __str__(self):
            raise RuntimeError("boom")

    dtype_map = {"bad": BrokenDtype()}

    result = apply_dtypes_and_casts(df, dtype_map, tz_cols=[], naive_dt_cols=[])

    assert result["bad"].dtype == object


def test_apply_dtypes_skips_missing_columns():
    df = pd.DataFrame({"a": [1, 2]})
    dtype_map = {"missing": pd.Int64Dtype()}

    result = apply_dtypes_and_casts(df, dtype_map, tz_cols=[], naive_dt_cols=[])

    assert result is df
    assert list(result.columns) == ["a"]
