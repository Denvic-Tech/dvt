from __future__ import annotations

import dask.dataframe as dd
import pandas as pd
import pytest

from src.node_dsl.exceptions import NodeValidationError
from src.nodes.transform import DataFrameGroupByAgg


def test_groupby_agg_keeps_null_groups_in_group_keys() -> None:
    pdf = pd.DataFrame(
        {
            "group": ["A", None, None],
            "value": [1, 1, None],
        }
    )
    node = DataFrameGroupByAgg(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-groupby-agg",
        df=dd.from_pandas(pdf, npartitions=2),
        group_by_columns=["group"],
        new_cols=["value_count"],
        source_cols=["value"],
        agg_funcs=["count"],
    )

    node.process()
    result = node.output.compute()

    assert len(result) == 2
    assert set(result.columns) == {"group", "value_count"}

    a_row = result[result["group"] == "A"].iloc[0]
    null_row = result[result["group"].isna()].iloc[0]
    assert int(a_row["value_count"]) == 1
    assert int(null_row["value_count"]) == 1


def test_groupby_agg_handles_index_column_name_conflict() -> None:
    pdf = pd.DataFrame(
        {
            "DealID": ["D1", "D1", "D2"],
            "ProjectID": ["P1", "P1", "P2"],
            "crm_1c_guid": ["G1", "G1", "G2"],
            "SumProject": [10.0, 5.0, 7.0],
        }
    )
    pdf.index = pd.Index(pdf["DealID"], name="DealID")

    node = DataFrameGroupByAgg(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-groupby-agg-index-conflict",
        df=dd.from_pandas(pdf, npartitions=2),
        group_by_columns=["ProjectID", "crm_1c_guid", "DealID"],
        new_cols=["SumProject_sum"],
        source_cols=["SumProject"],
        agg_funcs=["sum"],
    )

    node.process()
    result = (
        node.output.compute()
        .sort_values(["ProjectID", "crm_1c_guid", "DealID"])
        .reset_index(drop=True)
    )

    assert list(result.columns) == ["ProjectID", "crm_1c_guid", "DealID", "SumProject_sum"]
    assert result["SumProject_sum"].tolist() == [15.0, 7.0]


def test_groupby_agg_without_group_columns_aggregates_whole_dataframe() -> None:
    pdf = pd.DataFrame(
        {
            "value": [1, 2, 3, 4],
            "category": ["A", "A", "B", None],
        }
    )
    node = DataFrameGroupByAgg(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-groupby-agg-global",
        df=dd.from_pandas(pdf, npartitions=2),
        group_by_columns=[],
        new_cols=["value_sum", "value_count", "category_first", "category_last", "category_nunique"],
        source_cols=["value", "value", "category", "category", "category"],
        agg_funcs=["sum", "count", "first", "last", "nunique"],
    )

    node.process()
    result = node.output.compute().reset_index(drop=True)

    assert list(result.columns) == [
        "value_sum",
        "value_count",
        "category_first",
        "category_last",
        "category_nunique",
    ]
    assert len(result) == 1
    assert int(result.loc[0, "value_sum"]) == 10
    assert int(result.loc[0, "value_count"]) == 4
    assert result.loc[0, "category_first"] == "A"
    assert result.loc[0, "category_last"] == "B"
    assert int(result.loc[0, "category_nunique"]) == 2


def test_groupby_agg_without_group_columns_and_without_aggs_fails_validation() -> None:
    node = DataFrameGroupByAgg(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-groupby-agg-invalid-global",
        df=dd.from_pandas(pd.DataFrame({"value": [1, 2, 3]}), npartitions=1),
        group_by_columns=[],
        new_cols=None,
        source_cols=None,
        agg_funcs=None,
    )

    with pytest.raises(NodeValidationError, match="Either 'group_by_columns' or aggregation fields must be provided"):
        node.validate_agg()
