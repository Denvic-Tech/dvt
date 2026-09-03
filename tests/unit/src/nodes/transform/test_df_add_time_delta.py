from datetime import timedelta

import pytest

from src.node_dsl import NodeValidationError
from src.nodes.transform.df_add_time_delta import AddTimeDeltaToDataFrame
from src.pipeline.execution_mode import PipelineExecutionMode
from src.utils.testing import types_testing_dataframe


class TestAddTimedeltaToDataFrame:
    """ Группа тестов для AddTimeDelta ноды """

    @pytest.mark.asyncio
    async def test_add_time_delta_to_dataframe_success(self):
        """ Тестит правильное добавление timedelta к DataFrame """

        df = types_testing_dataframe(n_rows=100)

        df_column = df['datetime_col']
        df1_column = df_column.copy() + timedelta(days=1, hours=2, minutes=3)

        node = AddTimeDeltaToDataFrame(
            df=df,
            column_with_time='datetime_col',
            new_column_with_time='new_column',
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-delta",
            days=1,
            hours=2,
            minutes=3,
        )

        df['new_column'] = df1_column

        await node.execute(PipelineExecutionMode.FULL)
        assert node.output.equals(df)

    @pytest.mark.asyncio
    async def test_add_time_delta_validation_column_type(self):
        """ Тестит функции валидации ноды по типу колонки """
        df = types_testing_dataframe(n_rows=100)

        node = AddTimeDeltaToDataFrame(
            df=df,
            column_with_time='float_col',
            new_column_with_time='new_column',
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-delta",
            days=1,
            hours=2,
            minutes=3,
        )

        with pytest.raises(NodeValidationError):
            await node.validate()


    @pytest.mark.asyncio
    async def test_add_time_delta_validation_existing(self):
        """ Тестит функции валидации ноды по наличию в DataFrame """
        df = types_testing_dataframe(n_rows=100)

        node = AddTimeDeltaToDataFrame(
            df=df,
            column_with_time='NON_EXIST_COLUMN',
            new_column_with_time='new_column',
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-delta",
            days=1,
            hours=2,
            minutes=3,
        )

        with pytest.raises(NodeValidationError):
            await node.validate()