from datetime import timedelta

import pytest

from src.node_dsl import NodeValidationError
from src.nodes.transform.column_add_time_delta import ColumnAddTimeDelta
from src.pipeline.execution_mode import PipelineExecutionMode
from src.utils.testing import types_testing_dataframe


class TestAddTimedelta:
    """ Группа тестов для AddTimeDelta ноды """

    @pytest.mark.asyncio
    async def test_add_time_delta_node_computes_expected_column(self):
        """ Тестит правильное добавление timedelta к Series """
        df_column = types_testing_dataframe(n_rows=100)['datetime_col']
        df1_column = df_column.copy() + timedelta(days=1, hours=2, minutes=3)

        node = ColumnAddTimeDelta(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-delta",
            datetime_column=df_column,
            days=1,
            hours=2,
            minutes=3,
        )

        await node.execute(PipelineExecutionMode.FULL)
        assert node.output.equals(df1_column)

    @pytest.mark.asyncio
    async def test_add_time_delta_validation(self):
        """ Тестит функцию валидации ноды """
        df_column = types_testing_dataframe(n_rows=100)['float_col']

        node = ColumnAddTimeDelta(
            user_id="user",
            project_id="project",
            task_id="task",
            node_id="node-delta",
            datetime_column=df_column,
            days=1,
            hours=2,
            minutes=3,
        )
        with pytest.raises(NodeValidationError):
            await node.validate()
