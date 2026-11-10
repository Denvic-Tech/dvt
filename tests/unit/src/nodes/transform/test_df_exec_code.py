import dask.dataframe as dd
import pandas as pd

from core.types.dataframe_index import PhysicalDataFrameIndex
from core.utils.dataframe_index import get_physical_index, set_physical_index

from src.node_dsl.input_expressions import (
    ImmutableInputVariables,
    ImmutableProjectVariables,
)
from src.node_dsl.variables import VariableOutput
from src.nodes.transform.df_exec_code import DataFrameExecCode
from src.schemas.internal.project_variables import ProjectVariables


def test_df_exec_code_uses_shared_immutable_variable_views() -> None:
    index_name = "__dvt_partition_key"
    descriptor = PhysicalDataFrameIndex(
        name=index_name, strategy="range", source_column="value", bound_column="value"
    )
    pdf = pd.DataFrame([{"value": 1}]).set_index("value", drop=False).rename_axis(index_name)
    input_df = set_physical_index(dd.from_pandas(pdf, npartitions=1), descriptor)
    node = DataFrameExecCode(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-python-1",
        df=input_df,
        code=(
            "node.runtime_marker = (input_variables.shared, project_variables.shared)\n"
            "df_out = df_in"
        ),
        input_variables={
            "shared": VariableOutput(name="shared", value="input", type="STRING")
        },
        project_variables=ProjectVariables(
            variables={"shared": {"type": "STRING", "value": "project"}}
        ),
    )

    node.process()

    assert node.runtime_marker == ("input", "project")
    assert isinstance(node.immutable_input_variables, ImmutableInputVariables)
    assert isinstance(node.immutable_project_variables, ImmutableProjectVariables)
    assert node.output.compute().to_dict(orient="records") == [{"value": 1}]
    assert get_physical_index(node.output) is None
    assert get_physical_index(input_df) == descriptor
