import pytest

from src.nodes.transform.df_set_column_to_dataframe import SetColumnToDataFrame
from src.pipeline.execution_mode import PipelineExecutionMode
from src.utils.testing import types_testing_dataframe


class TestSetColumnToDataFrame:
    """ Группа тестов для SelectColumnFromDataFrame ноды """

    @pytest.mark.asyncio
    async def test_set_column_to_dataframe_success(self):
        """ Тестит получение Series по имени из Dataframe """
        df = types_testing_dataframe(n_rows=100)
        new_column = df['float_col'] + 1

        node = SetColumnToDataFrame(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-delta",
            column_data=new_column,
            df=df,
            column_name='new_column',
        )

        await node.execute(PipelineExecutionMode.FULL)
        assert node.output['new_column'].equals(new_column)
