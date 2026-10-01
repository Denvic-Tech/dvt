import dask.dataframe as dd
import pandas as pd
import pytest

from src.node_dsl.node_mixins.column_rules import apply_rules, build_plan, mask_matches
from src.nodes.transform._shared.column_rules import OPERATIONS
from src.nodes.transform.df_add_time_delta import AddTimeDeltaToDataFrame
from src.nodes.transform.df_replace_values import DataFrameReplaceValues


def rule(tokens, params, **kwargs):
    return {"id": kwargs.pop("id", "r"), "selector": {"tokens": tokens}, "params": params, **kwargs}


def test_masks_are_literal_except_wildcards():
    assert mask_matches("Проект_*", "Проект_один")
    assert mask_matches("a[1]?", "a[1]x")
    assert not mask_matches("a[1]?", "a1x")


def test_names_masks_types_exclusions_and_first_match():
    df = dd.from_pandas(pd.DataFrame({"Проект_a": ["x"], "Проект_b": ["x"], "n": [1]}), 1)
    first = rule([{"kind": "name", "value": "Проект_a"}], {"pattern": "x", "replacement": "a"})
    rest = rule([{"kind": "all"}], {"pattern": "x", "replacement": "b"}, id="rest")
    rest["selector"]["types"] = ["text"]
    result = apply_rules(df, [first, rest], OPERATIONS["regex"]).compute()
    assert result.iloc[0].to_dict() == {"Проект_a": "a", "Проект_b": "b", "n": 1}
    rest["selector"]["exclude"] = ["Проект_b"]
    assert [item.source for item in build_plan(df, [first, rest], OPERATIONS["regex"])] == [
        "Проект_a"
    ]


def test_dynamic_selection_and_output_collision():
    r = rule([{"kind": "mask", "value": "p_*"}], {"pattern": "x"})
    for columns in (["p_a"], ["p_a", "p_b"]):
        df = dd.from_pandas(pd.DataFrame({col: ["x"] for col in columns}), 1)
        assert len(build_plan(df, [r], OPERATIONS["regex"])) == len(columns)
    r["output"] = {"mode": "new", "names": {"p_a": "p_b"}, "suffix": "_copy"}
    with pytest.raises(ValueError, match="already exists"):
        build_plan(df, [r], OPERATIONS["regex"])


def test_missing_explicit_column_and_empty_match():
    df = dd.from_pandas(pd.DataFrame({"a": [1]}), 1)
    with pytest.raises(ValueError, match="not found"):
        build_plan(
            df,
            [rule([{"kind": "name", "value": "missing"}], {"pattern": "x"})],
            OPERATIONS["regex"],
        )
    assert (
        build_plan(
            df,
            [rule([{"kind": "mask", "value": "missing*"}], {"pattern": "x"})],
            OPERATIONS["regex"],
        )
        == []
    )


def test_replacement_null_empty_and_no_cascade():
    df = dd.from_pandas(pd.DataFrame({"a": ["", None, "x", "y"]}), 2)
    r = rule(
        [{"kind": "all"}],
        {
            "pairs": [
                {"old": "", "new": "empty"},
                {"old": None, "new": "null"},
                {"old": "x", "new": "y"},
                {"old": "y", "new": None},
            ]
        },
    )
    out = apply_rules(df, [r], OPERATIONS["replace"]).compute()["a"]
    assert out.iloc[:3].tolist() == ["empty", "null", "y"]
    assert pd.isna(out.iloc[3])


def test_replacement_coercion_is_per_column():
    df = dd.from_pandas(pd.DataFrame({"n": [1, 2], "s": ["1", "2"]}), 2)
    r = rule([{"kind": "all"}], {"pairs": [{"old": "1", "new": None}]})
    out = apply_rules(df, [r], OPERATIONS["replace"]).compute()
    assert out["n"].dtype == pd.Int64Dtype()
    assert out["n"].iloc[1] == 2
    assert out["s"].iloc[1] == "2"
    assert out.iloc[0].isna().all()


@pytest.mark.parametrize(
    "operation,params,expected",
    [
        ("timezone", {"timezone": "UTC"}, pd.Timestamp("2026-01-15", tz="UTC")),
        ("period", {"period": "month"}, pd.Timestamp("2026-01-01")),
        ("delta", {"days": 2}, pd.Timestamp("2026-01-17")),
    ],
)
def test_dates_multiple_columns(operation, params, expected):
    df = dd.from_pandas(
        pd.DataFrame({"a": pd.to_datetime(["2026-01-15"]), "b": pd.to_datetime(["2026-01-15"])}), 1
    )
    out = apply_rules(df, [rule([{"kind": "all"}], params)], OPERATIONS[operation]).compute()
    assert out["a"].iloc[0] == expected
    assert out["b"].iloc[0] == expected


def test_split_multiple_columns_and_collision():
    df = dd.from_pandas(pd.DataFrame({"a": ["a-b", "c"], "b": ["1-2", "3-4"]}), 2)
    r = rule([{"kind": "all"}], {"delimiter": "-", "drop_source": True})
    out = apply_rules(df, [r], OPERATIONS["split"]).compute()
    assert list(out.columns) == ["a_1", "a_2", "b_1", "b_2"]
    assert out["a_1"].tolist() == ["a", "c"]
    assert pd.isna(out["a_2"].iloc[1])
    with pytest.raises(ValueError, match="already exists"):
        build_plan(df.assign(a_1="exists"), [r], OPERATIONS["split"])


def test_expression_rules_read_original_data():
    df = dd.from_pandas(pd.DataFrame({"a": [1], "b": [2]}), 1)
    rules = [
        rule([{"kind": "name", "value": "a"}], {"expression": "__column__ + 10"}),
        rule([{"kind": "name", "value": "b"}], {"expression": "a + b"}, id="b"),
    ]
    assert apply_rules(df, rules, OPERATIONS["expression"]).compute().iloc[0].to_dict() == {
        "a": 11,
        "b": 3,
    }


def test_skip_incompatible_is_not_fallback():
    df = dd.from_pandas(pd.DataFrame({"a": ["x"]}), 1)
    r = rule([{"kind": "all"}], {"days": 1}, skip_incompatible=True)
    second = rule([{"kind": "all"}], {"days": 2}, id="second")
    assert build_plan(df, [r, second], OPERATIONS["delta"]) == []


@pytest.mark.asyncio
async def test_node_rules_do_not_require_legacy_inputs():
    df = dd.from_pandas(pd.DataFrame({"a": [1]}), 1)
    node = DataFrameReplaceValues(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="n",
        df=df,
        column_rules=[rule([{"kind": "all"}], {"pairs": [{"old": 1, "new": 2}]})],
    )
    await node.validate()
    node.process()
    assert node.output.compute()["a"].tolist() == [2]


@pytest.mark.asyncio
async def test_delta_legacy_hooks_do_not_validate_rules_as_single_column():
    df = dd.from_pandas(pd.DataFrame({"a": pd.to_datetime(["2026-01-01"])}), 1)
    node = AddTimeDeltaToDataFrame(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="n",
        df=df,
        column_rules=[rule([{"kind": "all"}], {"days": 1})],
    )
    await node.validate()
    node.process()
    assert node.output.compute()["a"].iloc[0] == pd.Timestamp("2026-01-02")


@pytest.mark.asyncio
async def test_calculated_columns_and_series_bindings_through_node_execution():
    from src.nodes.transform.df_add_column_by_expression import DataFrameAddColumnByExpression
    from src.nodes.transform.df_set_column_to_dataframe import SetColumnToDataFrame
    from src.pipeline.execution_mode import PipelineExecutionMode

    df = dd.from_pandas(pd.DataFrame({"a": [1, 2], "b": [3, 4]}, index=[10, 20]), 2)
    expression = DataFrameAddColumnByExpression(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="expr",
        df=df,
        calculated_columns=[
            {"name": "sum", "expression": "a + b"},
            {"name": "double", "expression": "a * 2"},
        ],
    )
    await expression.execute(PipelineExecutionMode.FULL)
    assert expression.output.compute()["sum"].tolist() == [4, 6]
    assert expression.output.compute()["double"].tolist() == [2, 4]

    # The Series index, rather than position, determines alignment.
    source = dd.from_pandas(pd.Series([8, 7], index=[20, 10], name="external"), 1)
    assignment = SetColumnToDataFrame(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="assign",
        df=df,
        column_data=[source, df["a"].rename("other")],
        column_bindings=[
            {"source": "external", "target": "new"},
            {"source": "other", "target": "copy"},
        ],
    )
    await assignment.execute(PipelineExecutionMode.FULL)
    result = assignment.output.compute()
    assert result["new"].tolist() == [7, 8]
    assert result["copy"].tolist() == [1, 2]


@pytest.mark.asyncio
async def test_expression_dependency_on_new_column_and_binding_collision_are_errors():
    from src.node_dsl import NodeValidationError
    from src.nodes.transform.df_add_column_by_expression import DataFrameAddColumnByExpression
    from src.nodes.transform.df_set_column_to_dataframe import SetColumnToDataFrame

    df = dd.from_pandas(pd.DataFrame({"a": [1]}), 1)
    expression = DataFrameAddColumnByExpression(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="expr",
        df=df,
        calculated_columns=[
            {"name": "b", "expression": "a + 1"},
            {"name": "c", "expression": "b + 1"},
        ],
    )
    with pytest.raises(Exception, match="b"):
        await expression.validate()
    assignment = SetColumnToDataFrame(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="assign",
        df=df,
        column_data=df["a"],
        column_bindings=[{"source": "a", "target": "a"}],
    )
    with pytest.raises(NodeValidationError, match="already exists"):
        await assignment.validate()


@pytest.mark.parametrize("pattern,replacement", [("[", ""), ("(a)", r"\2")])
def test_invalid_python_regex_is_rejected_before_execution(pattern, replacement):
    df = dd.from_pandas(pd.DataFrame({"a": ["a"]}), 1)
    with pytest.raises(ValueError):
        build_plan(
            df,
            [rule([{"kind": "all"}], {"pattern": pattern, "replacement": replacement})],
            OPERATIONS["regex"],
        )


@pytest.mark.asyncio
async def test_rule_metadata_and_serialized_runtime_inputs():
    from src.node_dsl.core.input_values import NodeInputConstantValue
    from src.node_dsl.registry.definitions import _create_node_base_definition
    from src.pipeline.execution_mode import PipelineExecutionMode
    from src.pipeline.graph_utils import build_node_kwargs
    from src.schemas.internal.node_data import NodeData

    rules = [
        rule(
            [{"kind": "all"}],
            {"pairs": [{"old": "x", "new": "y"}]},
            output={"mode": "new", "suffix": "_copy"},
        )
    ]
    definition = _create_node_base_definition(DataFrameReplaceValues)
    kwargs = build_node_kwargs(
        node_id="replace",
        node_def=definition,
        node_data=NodeData(
            name="DataFrameReplaceValues",
            inputs={"column_rules": NodeInputConstantValue(value=rules)},
        ),
        node_outputs={},
    )
    assert kwargs["column_rules"] == rules
    df = dd.from_pandas(pd.DataFrame({"a": ["x"]}), 1)
    node = DataFrameReplaceValues(
        user_id="u", project_id="p", task_id="t", node_id="replace", df=df, **kwargs
    )
    await node.execute(PipelineExecutionMode.METADATA_ONLY)
    assert list(node.output.columns) == ["a", "a_copy"]
