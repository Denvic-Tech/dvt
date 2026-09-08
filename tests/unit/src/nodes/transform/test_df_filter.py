from __future__ import annotations

import dask.dataframe as dd
import pandas as pd
import pytest
from pydantic import ValidationError

from src.node_dsl import IO
from src.node_dsl.variables import VariableOutput
from src.nodes.transform.df_filter import DataFrameFilter
from src.types import EMPTY_STRING_VALUE, NULL_VALUE


def _column(name: str) -> dict[str, str]:
    return {"type": "column", "column": name}


def _literal(value) -> dict[str, object]:
    return {"type": "literal", "value": value}


def _expression(value: str, expression_kind: str = "single") -> dict[str, object]:
    return {
        "type": "expression",
        "value": {
            "__dvt_type": "expr",
            "value": value,
            "expression_kind": expression_kind,
        },
    }


def _condition(
    left: dict[str, object],
    operator: str,
    right: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "kind": "condition",
        "left": left,
        "operator": operator,
        "right": right,
    }


def _and(*conditions: dict[str, object]) -> dict[str, object]:
    return {"kind": "and", "conditions": list(conditions)}


def _or(*conditions: dict[str, object]) -> dict[str, object]:
    return {"kind": "or", "conditions": list(conditions)}


def _build_node(
    df: pd.DataFrame,
    conditions: dict[str, object],
    *,
    input_variables: dict[str, object] | None = None,
) -> DataFrameFilter:
    return DataFrameFilter(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-filter",
        df=dd.from_pandas(df, npartitions=2),
        conditions=conditions,
        input_variables=input_variables or {},
    )


def test_filter_supports_business_partition_index_column() -> None:
    df = pd.DataFrame({"k": range(10), "value": range(100, 110)})
    df.index = pd.Index(df["k"], name="k")

    node = _build_node(
        df,
        _condition(_column("k"), ">=", _literal(5)),
    )
    node.process()

    result = node.output.compute()
    assert result["k"].tolist() == [5, 6, 7, 8, 9]
    assert result.index.name == "k"


def test_filter_supports_nested_and_or_tree() -> None:
    df = pd.DataFrame(
        {
            "name": ["Alice", "Bob", "Charlie", "Diana"],
            "age": [35, 20, 40, 25],
            "status": ["active", "active", "inactive", "inactive"],
            "deleted_at": pd.to_datetime([None, "2026-01-01", None, None]),
        }
    )

    conditions = _or(
        _and(
            _condition(_column("age"), ">=", _literal(30)),
            _condition(_column("status"), "==", _literal("active")),
        ),
        _condition(_column("deleted_at"), "==", _literal(NULL_VALUE)),
    )

    node = _build_node(df, conditions)
    node.process()

    result = node.output.compute()
    assert set(result["name"].tolist()) == {"Alice", "Charlie", "Diana"}


@pytest.mark.parametrize(
    ("conditions", "expected_values"),
    [
        (
            _condition(_column("left"), ">=", _column("right")),
            [2, 3],
        ),
        (
            _condition(_column("left"), "<", _column("right")),
            [1],
        ),
    ],
)
def test_filter_supports_column_vs_column_numeric(
    conditions: dict[str, object],
    expected_values: list[int],
) -> None:
    df = pd.DataFrame({"left": [1, 2, 3], "right": [2, 2, 1]})

    node = _build_node(df, conditions)
    node.process()

    result = node.output.compute()
    assert result["left"].tolist() == expected_values


def test_filter_supports_column_vs_column_datetime() -> None:
    df = pd.DataFrame(
        {
            "start_at": pd.to_datetime(["2026-01-01", "2026-01-03", "2026-01-05"]),
            "end_at": pd.to_datetime(["2026-01-02", "2026-01-02", "2026-01-05"]),
        }
    )

    node = _build_node(
        df,
        _condition(_column("end_at"), ">=", _column("start_at")),
    )
    node.process()

    result = node.output.compute()
    assert len(result) == 2
    assert result.index.tolist() == [0, 2]


def test_filter_supports_expression_right_operand_from_input_variables() -> None:
    df = pd.DataFrame({"name": ["A", "B", "C"], "age": [10, 20, 30]})

    node = _build_node(
        df,
        _condition(_column("age"), ">", _expression("param")),
        input_variables={
            "param": VariableOutput(name="param", type=IO.INT, value=15, var_type="user"),
        },
    )
    node.process()

    result = node.output.compute()
    assert result["name"].tolist() == ["B", "C"]


def test_filter_supports_calculated_expression_right_operand() -> None:
    df = pd.DataFrame({"name": ["A", "B", "C"], "age": [10, 20, 30]})

    node = _build_node(
        df,
        _condition(_column("age"), ">=", _expression("input_variables.base + 5")),
        input_variables={
            "base": VariableOutput(name="base", type=IO.INT, value=15, var_type="user"),
        },
    )
    node.process()

    result = node.output.compute()
    assert result["name"].tolist() == ["B", "C"]


def test_filter_supports_expression_list_right_operand() -> None:
    df = pd.DataFrame({"name": ["A", "B", "C"], "age": [10, 20, 30]})

    node = _build_node(
        df,
        _condition(_column("age"), "isin", _expression("allowed_ages")),
        input_variables={
            "allowed_ages": VariableOutput(
                name="allowed_ages",
                type=IO.JSON,
                value=[10, 30],
                var_type="user",
            ),
        },
    )
    node.process()

    result = node.output.compute()
    assert result["name"].tolist() == ["A", "C"]


def test_filter_rejects_template_expression_operand() -> None:
    df = pd.DataFrame({"age": [10, 20, 30]})

    node = _build_node(
        df,
        _condition(_column("age"), ">", _expression("{{ param }}", expression_kind="template")),
    )

    with pytest.raises(ValidationError, match="supports only 'single' expression_kind"):
        node.process()


def test_filter_raises_clear_error_for_missing_expression_variable() -> None:
    df = pd.DataFrame({"age": [10, 20, 30]})

    node = _build_node(
        df,
        _condition(_column("age"), ">", _expression("missing_param")),
    )

    with pytest.raises(ValueError, match="Could not resolve expression operand"):
        node.process()


def test_filter_keeps_mustache_literal_as_plain_string() -> None:
    df = pd.DataFrame({"age": [10, 20, 30]})

    node = _build_node(
        df,
        _condition(_column("age"), ">", _literal("{{param}}")),
    )

    with pytest.raises(TypeError, match="Invalid comparison between dtype=int64 and str"):
        node.process()


def test_filter_metadata_mode_does_not_evaluate_expression_operand() -> None:
    df = pd.DataFrame({"name": ["A", "B", "C"], "age": [10, 20, 30]})
    node = _build_node(
        df,
        _condition(_column("age"), ">", _expression("missing_param")),
    )

    node.process_metadata()

    pd.testing.assert_frame_equal(node.output.compute(), df, check_dtype=False)
    pd.testing.assert_frame_equal(node.inverted_output.compute(), df, check_dtype=False)


@pytest.mark.parametrize("null_literal", [None, NULL_VALUE])
def test_filter_treats_none_and_null_token_as_literal_null(null_literal) -> None:
    df = pd.DataFrame(
        {
            "name": ["A", "B", "C"],
            "deleted_at": pd.to_datetime([None, "2026-01-01", None]),
        }
    )

    node = _build_node(
        df,
        _condition(_column("deleted_at"), "==", _literal(null_literal)),
    )
    node.process()

    result = node.output.compute()
    assert result["name"].tolist() == ["A", "C"]


def test_filter_treats_empty_string_token_as_literal_empty_string() -> None:
    df = pd.DataFrame(
        {
            "name": ["A", "B", "C"],
            "status": ["", "active", ""],
        }
    )

    node = _build_node(
        df,
        _condition(_column("status"), "==", _literal(EMPTY_STRING_VALUE)),
    )
    node.process()

    result = node.output.compute()
    assert result["name"].tolist() == ["A", "C"]


def test_filter_treats_empty_string_token_inside_isin_list() -> None:
    df = pd.DataFrame(
        {
            "name": ["A", "B", "C", "D"],
            "status": ["", "active", "archived", ""],
        }
    )

    node = _build_node(
        df,
        _condition(_column("status"), "isin", _literal([EMPTY_STRING_VALUE, "active"])),
    )
    node.process()

    result = node.output.compute()
    assert result["name"].tolist() == ["A", "B", "D"]


def test_filter_rejects_relational_operator_with_null_literal() -> None:
    df = pd.DataFrame({"age": [10, 20, 30]})

    node = _build_node(
        df,
        _condition(_column("age"), ">", _literal(NULL_VALUE)),
    )

    with pytest.raises(ValueError, match="Relational operators do not support NULL literals"):
        node.process()


def test_filter_output_and_inverted_output_are_complements() -> None:
    df = pd.DataFrame({"name": ["A", "B", "C"], "age": [10, 20, 30]})

    node = _build_node(
        df,
        _condition(_column("age"), ">=", _literal(20)),
    )
    node.process()

    result = node.output.compute()
    inverted = node.inverted_output.compute()

    combined = pd.concat([result, inverted]).sort_index()
    pd.testing.assert_frame_equal(combined, df.sort_index(), check_dtype=False)


def test_filter_raises_for_missing_column() -> None:
    df = pd.DataFrame({"age": [1, 2, 3]})
    node = _build_node(
        df,
        _condition(_column("unknown"), "==", _literal(1)),
    )

    with pytest.raises(KeyError, match="Column 'unknown' not found"):
        node.process()


@pytest.mark.parametrize(
    "conditions,error_match",
    [
        (
            {"kind": "and", "conditions": []},
            "AND group must contain at least one condition",
        ),
        (
            _condition(_column("name"), "contains", _column("surname")),
            "supports only literal or expression right operand",
        ),
        (
            _condition(_column("name"), "isnull", _literal("x")),
            "must not define 'right'",
        ),
        (
            {"kind": "condition", "left": _column("age"), "operator": "=="},
            "requires 'right'",
        ),
    ],
)
def test_filter_validation_errors(
    conditions: dict[str, object],
    error_match: str,
) -> None:
    df = pd.DataFrame({"name": ["A"], "surname": ["B"], "age": [1]})
    node = _build_node(df, conditions)

    with pytest.raises(ValidationError, match=error_match):
        node.process()
