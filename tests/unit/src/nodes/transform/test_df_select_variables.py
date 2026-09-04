from __future__ import annotations

from datetime import datetime

import dask.dataframe as dd
import pandas as pd
import pytest

from src.node_dsl import IO, NodeValidationError
from src.nodes.transform.df_select_variables import DataFrameSelectVariables
from src.node_dsl.variables import UnresolvedValue, VariableOutput


def test_df_select_variables_emits_typed_variables_and_keeps_input_variables() -> None:
    pdf = pd.DataFrame(
        {
            "amount": [10, 15, 25],
            "city": ["Moscow", "Perm", "Tyumen"],
            "loaded_at": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        }
    )
    node = DataFrameSelectVariables(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-select-variables",
        df=dd.from_pandas(pdf, npartitions=2),
        input_variables={
            "existing": VariableOutput(
                name="existing",
                type=IO.STRING,
                value="keep-me",
                var_type="user",
            ),
        },
        selected_variables={
            "amount_total": {"source_column_name": "amount", "agg_func": "sum"},
            "amount_avg": {"source_column_name": "amount", "agg_func": "mean"},
            "row_count": {"source_column_name": "amount", "agg_func": "count"},
            "first_city": {"source_column_name": "city", "agg_func": "first"},
            "last_loaded_at": {"source_column_name": "loaded_at", "agg_func": "last"},
        },
    )

    node.process()

    assert node.output_variables == {
        "existing": VariableOutput(
            name="existing",
            type=IO.STRING,
            value="keep-me",
            var_type="user",
        ),
        "amount_total": VariableOutput(
            name="amount_total",
            type=IO.INT,
            value=50,
            var_type="user",
        ),
        "amount_avg": VariableOutput(
            name="amount_avg",
            type=IO.FLOAT,
            value=50 / 3,
            var_type="user",
        ),
        "row_count": VariableOutput(
            name="row_count",
            type=IO.INT,
            value=3,
            var_type="user",
        ),
        "first_city": VariableOutput(
            name="first_city",
            type=IO.STRING,
            value="Moscow",
            var_type="user",
        ),
        "last_loaded_at": VariableOutput(
            name="last_loaded_at",
            type=IO.DATETIME,
            value=datetime(2024, 1, 3),
            var_type="user",
        ),
    }


@pytest.mark.asyncio
async def test_df_select_variables_validation_fails_for_missing_columns() -> None:
    pdf = pd.DataFrame({"amount": [1, 2, 3]})
    node = DataFrameSelectVariables(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-select-variables-validation",
        df=dd.from_pandas(pdf, npartitions=1),
        selected_variables={
            "missing_value": {"source_column_name": "missing", "agg_func": "sum"},
        },
    )

    with pytest.raises(NodeValidationError, match="missing"):
        await node.validate()


def test_df_select_variables_process_metadata_emits_typed_unresolved_variables() -> None:
    pdf = pd.DataFrame(
        {
            "amount": pd.Series(dtype="int64"),
            "city": pd.Series(dtype="object"),
            "loaded_at": pd.Series(dtype="datetime64[ns]"),
        }
    )
    node = DataFrameSelectVariables(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-select-variables-metadata",
        df=dd.from_pandas(pdf, npartitions=1),
        selected_variables={
            "amount_total": {"source_column_name": "amount", "agg_func": "sum"},
            "amount_avg": {"source_column_name": "amount", "agg_func": "mean"},
            "first_city": {"source_column_name": "city", "agg_func": "first"},
            "last_loaded_at": {"source_column_name": "loaded_at", "agg_func": "last"},
        },
    )

    node.process_metadata()

    assert node.output_variables["amount_total"].type == IO.INT
    assert node.output_variables["amount_avg"].type == IO.FLOAT
    assert node.output_variables["first_city"].type == IO.STRING
    assert node.output_variables["last_loaded_at"].type == IO.DATETIME
    assert isinstance(node.output_variables["amount_total"].value, UnresolvedValue)
