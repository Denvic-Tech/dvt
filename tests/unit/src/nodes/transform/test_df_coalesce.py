import pandas as pd
import pytest
from dask import dataframe as dd

from src.node_dsl import NodeValidationError
from src.nodes.transform.df_coalesce import FillColumnNullValues
from src.pipeline.execution_mode import PipelineExecutionMode
from src.utils.testing import types_testing_dataframe


class TestFillColumnNullValues:
    """ Группа тестов для FillColumnNullValues ноды """

    @pytest.mark.asyncio
    async def test_fill_column_empty_values_success(self):
        """ Тестит заполнение Series значениями из другой Series """
        df = types_testing_dataframe(n_rows=100)
        df_column = df['category_with_null']
        df1_column = df['string_col']

        df_column = df_column.fillna(value=df1_column)

        node = FillColumnNullValues(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-delta",
            column_with_null=df_column,
            column_with_values=df1_column,
        )

        await node.execute(PipelineExecutionMode.FULL)
        assert node.output.equals(df_column)

    @pytest.mark.asyncio
    async def test_fill_column_empty_values_validation(self):
        """ Тестит функцию валидации ноды """
        df = types_testing_dataframe(n_rows=100)
        df_column = df['category_with_null']
        df1 = dd.from_pandas(pd.DataFrame(columns=['col1', 'col2', 'col3']), npartitions=1)
        df1 = df1['col1']

        node = FillColumnNullValues(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-delta",
            column_with_null=df_column,
            column_with_values=df1,
        )

        with pytest.raises(NodeValidationError):
            await node.validate()
