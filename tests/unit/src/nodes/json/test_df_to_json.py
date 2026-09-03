import json

import pandas as pd
import pytest
from dask import dataframe as dd

from src.nodes.json.df_to_json import DataFrameToJson


def _run_node(df: dd.DataFrame, *, orient: str):
    node = DataFrameToJson(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-df-to-json",
        df=df,
        orient=orient,
    )
    node.process()
    return node.output


@pytest.mark.parametrize("orient", ["columns", "index"])
def test_df_to_json_converts_to_python_dict(orient: str) -> None:
    pdf = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    ddf = dd.from_pandas(pdf, npartitions=1)

    output = _run_node(ddf, orient=orient)

    assert isinstance(output, dict)

    # Build expected using pandas JSON encoder to avoid pandas-version differences.
    expected = json.loads(pdf.to_json(orient=orient, date_format="iso", default_handler=str))
    assert output == expected


def test_df_to_json_tight_orient_contains_expected_keys() -> None:
    pdf = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    ddf = dd.from_pandas(pdf, npartitions=1)

    output = _run_node(ddf, orient="tight")

    assert isinstance(output, dict)
    assert "index" in output
    assert "columns" in output
    assert "data" in output


def test_df_to_json_serializes_datetimes_to_strings() -> None:
    pdf = pd.DataFrame({"dt": [pd.Timestamp("2024-01-01 12:34:56")]})
    ddf = dd.from_pandas(pdf, npartitions=1)

    output = _run_node(ddf, orient="columns")

    assert isinstance(output, dict)
    assert isinstance(output["dt"]["0"], str)

