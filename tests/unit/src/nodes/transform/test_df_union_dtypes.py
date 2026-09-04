from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest
from dask import dataframe as dd

from src.nodes.transform.df_union import DataFrameUnion


def _run_union(
    pdf1: pd.DataFrame,
    pdf2: pd.DataFrame,
    *,
    column_mapping: dict[str, str] | None = None,
    npartitions: int = 1,
) -> pd.DataFrame:
    node = DataFrameUnion(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-union",
        df1=dd.from_pandas(pdf1, npartitions=npartitions),
        df2=dd.from_pandas(pdf2, npartitions=npartitions),
        column_mapping=column_mapping or {},
    )
    node.process()
    return node.output.compute()


def test_union_datetime_ns_and_us_keeps_datetime_ns() -> None:
    pdf1 = pd.DataFrame(
        {
            "dt": pd.to_datetime(["2026-01-01 10:00:00", "2026-01-02 10:00:00"]).astype(
                "datetime64[ns]"
            )
        }
    )
    pdf2 = pd.DataFrame(
        {
            "dt": pd.to_datetime(["2026-01-03 10:00:00", "2026-01-04 10:00:00"]).astype(
                "datetime64[us]"
            )
        }
    )

    result = _run_union(pdf1, pdf2)

    assert str(result["dt"].dtype) == "datetime64[ns]"
    assert result["dt"].tolist() == pd.to_datetime(
        [
            "2026-01-01 10:00:00",
            "2026-01-02 10:00:00",
            "2026-01-03 10:00:00",
            "2026-01-04 10:00:00",
        ]
    ).tolist()


def test_union_datetime_naive_and_utc_tz_keeps_datetime_ns() -> None:
    pdf1 = pd.DataFrame({"dt": pd.to_datetime(["2026-01-01 10:00:00", "2026-01-02 10:00:00"])})
    pdf2 = pd.DataFrame({"dt": pd.to_datetime(["2026-01-03 10:00:00", "2026-01-04 10:00:00"], utc=True)})

    result = _run_union(pdf1, pdf2)

    assert str(result["dt"].dtype) == "datetime64[ns]"
    expected = pd.to_datetime(
        [
            "2026-01-01 10:00:00",
            "2026-01-02 10:00:00",
            "2026-01-03 10:00:00",
            "2026-01-04 10:00:00",
        ]
    )
    assert result["dt"].tolist() == expected.tolist()


def test_union_datetime_different_timezones_keeps_datetime_ns() -> None:
    pdf1 = pd.DataFrame(
        {
            "dt": pd.to_datetime(["2026-01-01 00:00:00", "2026-01-02 00:00:00"], utc=True).tz_convert(
                "Europe/Moscow"
            )
        }
    )
    pdf2 = pd.DataFrame(
        {
            "dt": pd.to_datetime(["2026-01-03 00:00:00", "2026-01-04 00:00:00"], utc=True).tz_convert(
                "Asia/Yekaterinburg"
            )
        }
    )

    result = _run_union(pdf1, pdf2)

    assert str(result["dt"].dtype) == "datetime64[ns]"
    expected = pd.to_datetime(
        [
            "2026-01-01 00:00:00",
            "2026-01-02 00:00:00",
            "2026-01-03 00:00:00",
            "2026-01-04 00:00:00",
        ]
    )
    assert result["dt"].tolist() == expected.tolist()


def test_union_datetime_mapped_columns_keep_datetime_ns() -> None:
    pdf1 = pd.DataFrame(
        {
            "Period": pd.to_datetime(["2026-02-01 12:00:00", "2026-03-01 12:00:00"]).astype(
                "datetime64[ns]"
            ),
            "value": [1, 2],
        }
    )
    pdf2 = pd.DataFrame(
        {
            "period_src": pd.to_datetime(["2026-04-01 12:00:00", "2026-05-01 12:00:00"], utc=True),
            "value": [3, 4],
        }
    )

    result = _run_union(pdf1, pdf2, column_mapping={"Period": "period_src"})

    assert "period_src" not in result.columns
    assert str(result["Period"].dtype) == "datetime64[ns]"
    assert result["value"].tolist() == [1, 2, 3, 4]


def test_union_datetime_and_string_same_column_not_forced_to_datetime() -> None:
    pdf1 = pd.DataFrame({"dt": pd.to_datetime(["2026-01-01", "2026-01-02"])})
    pdf2 = pd.DataFrame({"dt": pd.Series(["bad", "2026-01-03"], dtype="string")})

    result = _run_union(pdf1, pdf2)

    assert str(result["dt"].dtype) in {"object", "string"}
    assert "bad" in result["dt"].astype("string").tolist()


def test_union_timedelta_column_preserved() -> None:
    pdf1 = pd.DataFrame({"delta": pd.to_timedelta([1, 2], unit="D")})
    pdf2 = pd.DataFrame({"delta": pd.to_timedelta([3, 4], unit="D")})

    result = _run_union(pdf1, pdf2)

    assert pd.api.types.is_timedelta64_dtype(result["delta"].dtype)
    assert result["delta"].tolist() == pd.to_timedelta([1, 2, 3, 4], unit="D").tolist()


def test_union_nullable_integer_and_integer_not_degraded_to_string() -> None:
    pdf1 = pd.DataFrame({"num": pd.Series([1, None], dtype="Int64")})
    pdf2 = pd.DataFrame({"num": pd.Series([3, 4], dtype="int64")})

    result = _run_union(pdf1, pdf2)

    assert str(result["num"].dtype) == "Int64"
    assert result["num"].tolist() == [1, pd.NA, 3, 4]


def test_union_boolean_nullable_and_bool_not_degraded_to_string() -> None:
    pdf1 = pd.DataFrame({"flag": pd.Series([True, None], dtype="boolean")})
    pdf2 = pd.DataFrame({"flag": pd.Series([False, True], dtype="bool")})

    result = _run_union(pdf1, pdf2)

    assert str(result["flag"].dtype) == "boolean"
    assert result["flag"].tolist() == [True, pd.NA, False, True]


def test_union_category_with_different_categories_preserved() -> None:
    pdf1 = pd.DataFrame(
        {"status": pd.Categorical(["new", "in_progress"], categories=["new", "in_progress", "done"])}
    )
    pdf2 = pd.DataFrame({"status": pd.Categorical(["done", "new"], categories=["new", "done"])})

    result = _run_union(pdf1, pdf2)

    assert isinstance(result["status"].dtype, pd.CategoricalDtype)
    assert result["status"].astype("string").tolist() == ["new", "in_progress", "done", "new"]


def test_union_float32_and_float64_not_degraded_to_string() -> None:
    pdf1 = pd.DataFrame({"amount": pd.Series([1.5, 2.5], dtype="float32")})
    pdf2 = pd.DataFrame({"amount": pd.Series([3.5, 4.5], dtype="float64")})

    result = _run_union(pdf1, pdf2)

    assert pd.api.types.is_float_dtype(result["amount"].dtype)
    assert result["amount"].tolist() == [1.5, 2.5, 3.5, 4.5]


def test_union_decimal_object_and_float_values_preserved() -> None:
    pdf1 = pd.DataFrame({"val": pd.Series([Decimal("1.10"), Decimal("2.20")], dtype=object)})
    pdf2 = pd.DataFrame({"val": pd.Series([3.3, 4.4], dtype="float64")})

    result = _run_union(pdf1, pdf2)

    assert len(result) == 4
    assert float(result["val"].iloc[0]) == pytest.approx(1.10)
    assert float(result["val"].iloc[1]) == pytest.approx(2.20)
    assert float(result["val"].iloc[2]) == pytest.approx(3.3)
    assert float(result["val"].iloc[3]) == pytest.approx(4.4)


def test_union_complex_mixed_types_with_column_mapping() -> None:
    pdf1 = pd.DataFrame(
        {
            "Period": pd.to_datetime(["2026-01-01 00:00:00", "2026-01-02 00:00:00"]),
            "ID": pd.Series([1, None], dtype="Int64"),
            "Amount": pd.Series([10.5, 20.25], dtype="float32"),
            "Flag": pd.Series([True, None], dtype="boolean"),
            "Category": pd.Categorical(["A", "B"], categories=["A", "B", "C"]),
            "Text": pd.Series(["x", "y"], dtype="string"),
        }
    )
    pdf2 = pd.DataFrame(
        {
            "period_src": pd.to_datetime(["2026-01-03 00:00:00", "2026-01-04 00:00:00"], utc=True),
            "id_src": pd.Series([3, 4], dtype="int64"),
            "amount_src": pd.Series([30.0, 40.0], dtype="float64"),
            "flag_src": pd.Series([False, True], dtype="bool"),
            "category_src": pd.Categorical(["C", "A"], categories=["A", "C"]),
            "text_src": pd.Series(["z", "w"], dtype="object"),
        }
    )

    result = _run_union(
        pdf1,
        pdf2,
        column_mapping={
            "Period": "period_src",
            "ID": "id_src",
            "Amount": "amount_src",
            "Flag": "flag_src",
            "Category": "category_src",
            "Text": "text_src",
        },
    )

    assert str(result["Period"].dtype) == "datetime64[ns]"
    assert str(result["ID"].dtype) == "Int64"
    assert pd.api.types.is_float_dtype(result["Amount"].dtype)
    assert str(result["Flag"].dtype) == "boolean"
    assert isinstance(result["Category"].dtype, pd.CategoricalDtype)
    assert result["Text"].astype("string").tolist() == ["x", "y", "z", "w"]
    assert len(result) == 4


@pytest.mark.parametrize(
    ("dtype_left", "dtype_right", "values_left", "values_right"),
    [
        ("int32", "int64", [1, 2], [3, 4]),
        ("float32", "float64", [1.1, 2.2], [3.3, 4.4]),
        ("string", "object", ["a", "b"], ["c", "d"]),
        ("boolean", "bool", [True, False], [False, True]),
    ],
)
def test_union_type_pairs_values_are_preserved(
    dtype_left: str,
    dtype_right: str,
    values_left: list[object],
    values_right: list[object],
) -> None:
    left = pd.Series(values_left, dtype=dtype_left)
    right = pd.Series(values_right, dtype=dtype_right)

    pdf1 = pd.DataFrame({"col": left})
    pdf2 = pd.DataFrame({"col": right})

    result = _run_union(pdf1, pdf2)

    assert len(result) == 4
    if "float" in dtype_left or "float" in dtype_right:
        assert result["col"].astype("float64").tolist() == pytest.approx(values_left + values_right)
    else:
        expected = [str(v) for v in values_left + values_right]
        assert result["col"].astype("string").tolist() == expected

    if dtype_left in {"int32", "int64", "float32", "float64", "boolean"}:
        assert str(result["col"].dtype) != "string"


def test_union_partitions_more_than_one_keeps_datetime_dtype() -> None:
    pdf1 = pd.DataFrame(
        {
            "dt": pd.to_datetime(
                np.array(["2026-02-01 08:00:00", "2026-02-02 08:00:00", "2026-02-03 08:00:00"])
            )
        }
    )
    pdf2 = pd.DataFrame(
        {
            "dt": pd.to_datetime(
                np.array(["2026-02-04 08:00:00", "2026-02-05 08:00:00", "2026-02-06 08:00:00"]),
                utc=True,
            )
        }
    )

    result = _run_union(pdf1, pdf2, npartitions=2)

    assert str(result["dt"].dtype) == "datetime64[ns]"
    assert len(result) == 6
