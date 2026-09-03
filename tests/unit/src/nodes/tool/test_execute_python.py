import dask.dataframe as dd
import pandas as pd
import pytest

from src.node_dsl import registry
from src.node_dsl.input_expressions import (
    ImmutableInputVariables,
    ImmutableProjectVariables,
)
from src.node_dsl.variables import VariableOutput
from src.nodes.tool.execute_python import ExecutePython
from src.schemas.internal.project_variables import ProjectVariables


def _build_node(
        *,
        code: str,
        input_variables=None,
        project_variables=None,
        df_in=None,
        json_in=None,
) -> ExecutePython:
    return ExecutePython(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-python-1",
        code=code,
        df_in=df_in,
        json_in=json_in,
        input_variables=input_variables or {},
        project_variables=project_variables or ProjectVariables(variables={}),
    )


def test_execute_python_runs_code_and_emits_signal():
    node = _build_node(code="node.runtime_marker = 'executed'")

    node.process()

    assert node.runtime_marker == "executed"
    assert node.signal_out is True
    assert node.output is None
    assert node.output_json is None


@pytest.mark.asyncio
async def test_execute_python_inputs_are_optional_when_omitted():
    node = ExecutePython(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-python-1",
        code="node.runtime_marker = (df_in, json_in)",
        project_variables=ProjectVariables(variables={}),
    )

    await node.validate()

    assert node.df_in is None
    assert node.json_in is None


def test_execute_python_input_definitions_are_optional():
    definition = registry.get_definition("ExecutePython")

    assert definition.input_definitions["df_in"].optional is True
    assert definition.input_definitions["json_in"].optional is True


def test_execute_python_exposes_input_variables_as_read_only_object():
    node = _build_node(
        code="node.runtime_marker = input_variables.sample_value",
        input_variables={"sample_value": VariableOutput(
            name="sample_value",
            value="value-from-vars",
            type="STRING",
        )},
    )

    node.process()

    assert node.runtime_marker == "value-from-vars"
    assert isinstance(node.immutable_input_variables, ImmutableInputVariables)


def test_execute_python_exposes_project_variables_as_read_only_object() -> None:
    node = _build_node(
        code=(
            "node.runtime_marker = "
            "(project_variables.sample_limit, project_variables['sample_limit'])"
        ),
        project_variables=ProjectVariables(
            variables={"sample_limit": {"type": "INT", "value": 9}}
        ),
    )

    node.process()

    assert node.runtime_marker == (9, 9)
    assert isinstance(node.immutable_project_variables, ImmutableProjectVariables)


def test_execute_python_keeps_input_and_project_variables_separate() -> None:
    node = _build_node(
        code=(
            "node.runtime_marker = "
            "(input_variables.shared, project_variables.shared)"
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


def test_execute_python_rejects_input_variable_mutation():
    node = _build_node(
        code="input_variables['sample_value'] = 'mutated'",
        input_variables={"sample_value": VariableOutput(
            name="sample_value",
            value="value-from-vars",
            type="STRING",
        )},
    )

    with pytest.raises(ValueError, match="Error in provided Python code"):
        node.process()


def test_execute_python_rejects_project_variable_mutation():
    node = _build_node(
        code="project_variables['sample_value'] = 'mutated'",
        project_variables=ProjectVariables(
            variables={"sample_value": {"type": "STRING", "value": "original"}}
        ),
    )

    with pytest.raises(ValueError, match="Error in provided Python code"):
        node.process()


def test_execute_python_raises_on_empty_code():
    node = _build_node(code="   ")

    with pytest.raises(ValueError, match="Python code is empty"):
        node.process()


def test_execute_python_wraps_execution_errors():
    node = _build_node(code="raise RuntimeError('boom')")

    with pytest.raises(ValueError, match="Error in provided Python code"):
        node.process()


def test_execute_python_populates_dataframe_and_json_outputs():
    node = _build_node(
        code=(
            "df_out = pd.DataFrame([{'value': 1}, {'value': 2}])\n"
            "json_out = {'tags': {'b', 'a'}, 'created_at': pd.Timestamp('2024-01-02T03:04:05')}"
        )
    )

    node.process()

    assert node.signal_out is True
    assert isinstance(node.output, dd.DataFrame)
    assert node.output.compute().to_dict(orient="records") == [
        {"value": 1},
        {"value": 2},
    ]
    assert node.output_json == {
        "tags": ["a", "b"],
        "created_at": "2024-01-02T03:04:05",
    }


def test_execute_python_exposes_dataframe_and_json_inputs():
    input_df = dd.from_pandas(pd.DataFrame([{"value": 4}, {"value": 5}]), npartitions=1)
    node = _build_node(
        code="df_out = df_in.assign(total=df_in['value'] + 1)\njson_out = {'source': json_in['source']}",
        df_in=input_df,
        json_in={"source": "api"},
    )

    node.process()

    assert isinstance(node.output, dd.DataFrame)
    assert node.output.compute().to_dict(orient="records") == [
        {"value": 4, "total": 5},
        {"value": 5, "total": 6},
    ]
    assert node.output_json == {"source": "api"}


def test_execute_python_accepts_dask_dataframe_output():
    node = _build_node(
        code="df_out = dd.from_pandas(pd.DataFrame([{'value': 9}]), npartitions=1)"
    )

    node.process()

    assert isinstance(node.output, dd.DataFrame)
    assert node.output.compute().to_dict(orient="records") == [{"value": 9}]


def test_execute_python_rejects_invalid_dataframe_output_type():
    node = _build_node(code="df_out = {'value': 1}")

    with pytest.raises(ValueError, match="df_out"):
        node.process()


def test_execute_python_rejects_invalid_json_output_type():
    node = _build_node(
        code=(
            "class Unsupported:\n"
            "    pass\n"
            "json_out = {'payload': Unsupported()}"
        )
    )

    with pytest.raises(ValueError, match="json_out"):
        node.process()


@pytest.mark.asyncio
async def test_execute_python_process_metadata_does_not_execute_user_code():
    node = _build_node(code="raise RuntimeError('should not run in metadata mode')")

    await node.process_metadata()

    assert node.signal_out is True
    assert isinstance(node.output, dd.DataFrame)
    assert node.output.compute().empty is True
    assert list(node.output.columns) == []
    assert node.output_json == {}
