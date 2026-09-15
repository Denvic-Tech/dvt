import pandas as pd

from src.nodes.extract.load_excel import LoadExcel


def _make_node(*, dtypes, decimal=".", thousands=None) -> LoadExcel:
    return LoadExcel(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="load-excel-node",
        connection=object(),
        path="reports/data.xlsx",
        dtypes=dtypes,
        decimal=decimal,
        thousands=thousands,
    )


def test_explicit_dtypes_coerce_invalid_values_to_na() -> None:
    node = _make_node(
        dtypes={"i": "Int64", "f": "Float64", "b": "boolean", "s": "string"}
    )
    df = pd.DataFrame(
        {
            "i": ["3", "3.7", "abc", 5, None],
            "f": ["1.5", "x", 2, None, "3"],
            "b": ["true", "FALSE", 1, 0, "maybe"],
            "s": [1, "a", None, 2, 3],
        }
    )

    result = node._normalize_dataframe_dtypes(df)

    # Int64: "3.7" (дробное) и "abc" не подходят под целочисленный тип -> NA
    assert str(result["i"].dtype) == "Int64"
    assert result["i"].isna().tolist() == [False, True, True, False, True]
    assert result["i"].dropna().tolist() == [3, 5]

    # Float64: "x" -> NA, остальное число
    assert str(result["f"].dtype) == "Float64"
    assert result["f"].isna().tolist() == [False, True, False, True, False]
    assert result["f"].dropna().tolist() == [1.5, 2.0, 3.0]

    # boolean: "maybe" -> NA, числа 1/0 и строки true/false распознаны
    assert str(result["b"].dtype) == "boolean"
    assert result["b"].isna().tolist() == [False, False, False, False, True]
    assert result["b"].dropna().tolist() == [True, False, True, False]

    # string: None -> NA, остальное строкой
    assert str(result["s"].dtype) == "string"
    assert result["s"].isna().tolist() == [False, False, True, False, False]
    assert result["s"].dropna().tolist() == ["1", "a", "2", "3"]


def test_numeric_coercion_respects_decimal_and_thousands_separators() -> None:
    node = _make_node(dtypes={"amount": "Float64"}, decimal=",", thousands=" ")
    df = pd.DataFrame({"amount": ["1 234,5", "10,0", "нет", None]})

    result = node._normalize_dataframe_dtypes(df)

    assert str(result["amount"].dtype) == "Float64"
    assert result["amount"].isna().tolist() == [False, False, True, True]
    assert result["amount"].dropna().tolist() == [1234.5, 10.0]


def test_int_coercion_keeps_whole_floats_and_drops_fractional() -> None:
    node = _make_node(dtypes={"qty": "Int64"})
    df = pd.DataFrame({"qty": [5.0, 5.4, "7", "7.9", None]})

    result = node._normalize_dataframe_dtypes(df)

    assert str(result["qty"].dtype) == "Int64"
    assert result["qty"].isna().tolist() == [False, True, False, True, True]
    assert result["qty"].dropna().tolist() == [5, 7]
