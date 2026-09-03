import dask.dataframe as dd
import pandas as pd
import pytest

from src.nodes.transform.df_cast_column_type import DataFrameCastColumnType
from src.pipeline.execution_mode import PipelineExecutionMode


@pytest.mark.asyncio
async def test_cast_datetime64_ns_handles_mixed_tz_and_naive_values():
    source = pd.DataFrame(
        {
            "Period": [
                "2026-01-01 12:00:00",
                "2026-01-01T12:00:00+03:00",
                None,
            ]
        }
    )
    ddf = dd.from_pandas(source, npartitions=1)

    node = DataFrameCastColumnType(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="n",
        df=ddf,
        dtypes={"Period": "datetime64[ns]"},
    )

    await node.execute(PipelineExecutionMode.FULL)
    result = node.output.compute()

    expected = pd.to_datetime(source["Period"], errors="coerce", utc=True).dt.tz_localize(None)
    expected = expected.astype("datetime64[ns]")
    expected.name = "Period"

    assert str(result["Period"].dtype) == "datetime64[ns]"
    pd.testing.assert_series_equal(result["Period"], expected)


@pytest.mark.asyncio
async def test_cast_mixed_datetime_and_plain_dtypes():
    source = pd.DataFrame(
        {
            "Period": ["2026-01-01 00:00:00", "2026-01-02T03:00:00+03:00"],
            "Amount": ["10.5", "20.0"],
        }
    )
    ddf = dd.from_pandas(source, npartitions=1)

    node = DataFrameCastColumnType(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="n",
        df=ddf,
        dtypes={"Period": "datetime64[ns]", "Amount": "float64"},
    )

    await node.execute(PipelineExecutionMode.FULL)
    result = node.output.compute()

    assert str(result["Period"].dtype) == "datetime64[ns]"
    assert str(result["Amount"].dtype) == "float64"
    assert result["Amount"].tolist() == [10.5, 20.0]


@pytest.mark.asyncio
async def test_cast_integer_dtype_truncates_fractional_values_like_python_int():
    source = pd.DataFrame(
        {
            "close_in_min": [1.9, -1.9, 2.0, None],
        }
    )
    ddf = dd.from_pandas(source, npartitions=1)

    node = DataFrameCastColumnType(
        user_id="u",
        project_id="p",
        task_id="t",
        node_id="n",
        df=ddf,
        dtypes={"close_in_min": "Int64"},
    )

    await node.execute(PipelineExecutionMode.FULL)
    result = node.output.compute()

    expected = pd.Series([1, -1, 2, pd.NA], name="close_in_min", dtype="Int64")

    assert str(result["close_in_min"].dtype) == "Int64"
    pd.testing.assert_series_equal(result["close_in_min"], expected)
