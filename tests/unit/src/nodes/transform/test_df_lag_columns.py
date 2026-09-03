import dask.dataframe as dd
import pandas as pd
import pytest

from src.nodes.transform.df_lag_columns import DataFrameLagColumns
from src.pipeline.execution_mode import PipelineExecutionMode


@pytest.mark.asyncio
async def test_dataframe_lag_columns_all_types():
    """Тест создания лагов для колонок разных типов"""
    df = pd.DataFrame({
        'int_col': [1, 2, 3, 4, 5],
        'float_col': [1.1, 2.2, 3.3, 4.4, 5.5],
        'str_col': ['a', 'b', 'c', 'd', 'e'],
        'bool_col': [True, False, True, False, True],
        'datetime_col': pd.date_range('2021-01-01', periods=5),
        'cat_col': pd.Categorical(['A', 'B', 'C', 'A', 'B']),
    })

    ddf = dd.from_pandas(df, npartitions=1)

    # Тест 1: Целочисленная колонка с целым fill_value
    node = DataFrameLagColumns(user_id="user",
                               project_id="project",
                               task_id="task",
                               node_id="node-lag",
                               df=ddf,
                               columns_to_lag=['int_col'],
                               lag_steps=1,
                               fill_value=0)

    await node.execute(PipelineExecutionMode.FULL)
    result = node.output.compute()

    assert 'int_col_lag1' in result.columns
    expected_int = [0, 1, 2, 3, 4]
    pd.testing.assert_series_equal(
        result['int_col_lag1'],
        pd.Series(expected_int, name='int_col_lag1'),
        check_dtype=False
    )


@pytest.mark.asyncio
async def test_dataframe_lag_columns_edge_cases():
    """Тест пограничных случаев"""
    # Тест 1: Отрицательный лаг
    df = pd.DataFrame({
        'values': [10, 20, 30, 40, 50],
    })

    ddf = dd.from_pandas(df, npartitions=1)

    node1 = DataFrameLagColumns(user_id="user",
                                project_id="project",
                                task_id="task",
                                node_id="node-lag",
                                df=ddf,
                                columns_to_lag=['values'],
                                lag_steps=-1,
                                fill_value=999)

    await node1.execute(PipelineExecutionMode.FULL)
    result1 = node1.output.compute()
    expected = [20, 30, 40, 50, 999]
    pd.testing.assert_series_equal(
        result1['values_lag-1'],
        pd.Series(expected, name='values_lag-1'),
        check_dtype=False
    )

    # Тест 2: Лаг больше длины DataFrame
    node2 = DataFrameLagColumns(user_id="user",
                                project_id="project",
                                task_id="task",
                                node_id="node-lag",
                                df=ddf,
                                columns_to_lag=['values'],
                                lag_steps=10,
                                fill_value=0)
    node2.df = ddf
    node2.columns_to_lag = ['values']
    node2.lag_steps = 10  # Больше, чем строк в DataFrame
    node2.fill_value = 0

    await node2.execute(PipelineExecutionMode.FULL)
    result2 = node2.output.compute()
    expected2 = [0, 0, 0, 0, 0]
    pd.testing.assert_series_equal(
        result2['values_lag10'],
        pd.Series(expected2, name='values_lag10'),
        check_dtype=False
    )


@pytest.mark.asyncio
async def test_dataframe_lag_columns_empty_dataframe():
    """Тест с пустым DataFrame"""
    df = pd.DataFrame({
        'col1': [],
        'col2': []
    })

    ddf = dd.from_pandas(df, npartitions=1)

    node = DataFrameLagColumns(user_id="user",
                               project_id="project",
                               task_id="task",
                               node_id="node-lag",
                               df=ddf,
                               columns_to_lag=['col1'],
                               lag_steps=1,
                               fill_value=0)

    # Должно работать без ошибок (просто создаст пустую колонку)
    await node.execute(PipelineExecutionMode.FULL)
    result = node.output.compute()
    assert 'col1_lag1' in result.columns
    assert len(result) == 0
