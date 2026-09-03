import dask.dataframe as dd
import pandas as pd
import pandas.testing as pdt
import pytest

from src.nodes.transform.df_fill_na import DataFrameFillNA
from src.pipeline.execution_mode import PipelineExecutionMode


def _node(df: dd.DataFrame, fill_values: dict):
    return DataFrameFillNA(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-fill-na",
        df=df,
        fill_values=fill_values,
    )


class TestDataFrameFillNA:
    @pytest.mark.asyncio
    async def test_fill_na_by_column_function_mapping(self):
        pdf = pd.DataFrame(
            {
                "category": ["a", None, "a", "c"],
                "amount": [1.5, None, 3.0, 5.5],
                "untouched": [None, "kept", None, "also kept"],
            }
        )
        df = dd.from_pandas(pdf, npartitions=1)

        node = _node(df, {"category": "mode", "amount": "mean"})

        await node.execute(PipelineExecutionMode.FULL)

        expected = pd.DataFrame(
            {
                "category": ["a", "a", "a", "c"],
                "amount": [1.5, 10.0 / 3.0, 3.0, 5.5],
                "untouched": [None, "kept", None, "also kept"],
            }
        )
        pdt.assert_frame_equal(node.output.compute(), expected, check_dtype=False)

    @pytest.mark.asyncio
    async def test_fill_na_with_forward_and_backward_fill(self):
        pdf = pd.DataFrame(
            {
                "forward": [1.0, None, 3.0],
                "backward": [None, 2.0, 3.0],
            }
        )
        df = dd.from_pandas(pdf, npartitions=1)

        node = _node(df, {"forward": "ffill", "backward": "bfill"})

        await node.execute(PipelineExecutionMode.FULL)

        expected = pd.DataFrame(
            {
                "forward": [1.0, 1.0, 3.0],
                "backward": [2.0, 2.0, 3.0],
            }
        )
        pdt.assert_frame_equal(node.output.compute(), expected, check_dtype=False)

    @pytest.mark.asyncio
    async def test_validate_rejects_empty_mapping(self):
        df = dd.from_pandas(pd.DataFrame({"a": [None]}), npartitions=1)
        node = _node(df, {})

        with pytest.raises(ValueError, match="fill_values must be a non-empty dictionary"):
            await node.validate()

    @pytest.mark.asyncio
    async def test_validate_rejects_unknown_columns(self):
        df = dd.from_pandas(pd.DataFrame({"a": [None]}), npartitions=1)
        node = _node(df, {"missing": "mean"})

        with pytest.raises(ValueError, match="Columns not found in DataFrame"):
            await node.validate()

    @pytest.mark.asyncio
    async def test_validate_rejects_unknown_functions(self):
        df = dd.from_pandas(pd.DataFrame({"a": [None]}), npartitions=1)
        node = _node(df, {"a": "unknown"})

        with pytest.raises(ValueError, match="Unsupported fill NA functions"):
            await node.validate()
