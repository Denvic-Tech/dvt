from datetime import datetime, timedelta

import pandas as pd
import pytest

from src.node_dsl import IO, NodeValidationError
from src.node_dsl.variables import UnresolvedValue, VariableOutput
from src.nodes.transform.convert_variables_to_dataframe import ConvertVariablesToDataFrame


def test_convert_variables_to_dataframe_builds_single_row_ddf() -> None:
    node = ConvertVariablesToDataFrame(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-convert-variables",
        input_variables={
            "name": VariableOutput(name="name", type=IO.STRING, value="Alice", var_type="user"),
            "is_active": VariableOutput(name="is_active", type=IO.BOOLEAN, value=True, var_type="user"),
            "count": VariableOutput(name="count", type=IO.INT, value=7, var_type="user"),
            "ratio": VariableOutput(name="ratio", type=IO.FLOAT, value=1.5, var_type="user"),
            "loaded_at": VariableOutput(
                name="loaded_at",
                type=IO.DATETIME,
                value=datetime(2024, 1, 2, 3, 4, 5),
                var_type="user",
            ),
            "delay": VariableOutput(
                name="delay",
                type=IO.TIMEDELTA,
                value=timedelta(minutes=5),
                var_type="user",
            ),
            "payload": VariableOutput(
                name="payload",
                type=IO.JSON,
                value={"source": "api"},
                var_type="user",
            ),
        },
    )

    node.process()

    result = node.output.compute()
    row = result.to_dict(orient="records")[0]

    assert len(result) == 1
    assert row["name"] == "Alice"
    assert row["is_active"] is True
    assert row["count"] == 7
    assert row["ratio"] == 1.5
    assert row["loaded_at"] == pd.Timestamp(datetime(2024, 1, 2, 3, 4, 5))
    assert row["delay"] == pd.Timedelta(minutes=5)
    assert row["payload"] == {"source": "api"}
    assert str(result["name"].dtype) == "string"
    assert str(result["is_active"].dtype) == "boolean"
    assert str(result["count"].dtype) == "Int64"
    assert str(result["ratio"].dtype) == "float64"
    assert str(result["loaded_at"].dtype) == "datetime64[ns]"
    assert str(result["delay"].dtype) == "timedelta64[ns]"
    assert str(result["payload"].dtype) == "object"


def test_convert_variables_to_dataframe_keeps_list_variables_as_object_cells() -> None:
    node = ConvertVariablesToDataFrame(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-convert-variables-list",
        input_variables={
            "numbers": VariableOutput(
                name="numbers",
                type=IO.INT,
                value=[1, 2, 3],
                var_type="user",
                is_list_type=True,
            ),
        },
    )

    node.process()

    result = node.output.compute()

    assert result.to_dict(orient="records") == [{"numbers": [1, 2, 3]}]
    assert str(result["numbers"].dtype) == "object"


def test_convert_variables_to_dataframe_process_metadata_builds_typed_empty_ddf() -> None:
    node = ConvertVariablesToDataFrame(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-convert-variables-metadata",
        input_variables={
            "title": VariableOutput(name="title", type=IO.STRING, value="ignored", var_type="user"),
            "amount": VariableOutput(name="amount", type=IO.INT, value=1, var_type="user"),
            "payload": VariableOutput(name="payload", type=IO.JSON, value={"a": 1}, var_type="user"),
        },
    )

    node.process_metadata()

    result = node.output.compute()

    assert result.empty
    assert list(result.columns) == ["title", "amount", "payload"]
    assert str(result["title"].dtype) == "string"
    assert str(result["amount"].dtype) == "Int64"
    assert str(result["payload"].dtype) == "object"


def test_convert_variables_to_dataframe_rejects_unresolved_values_in_full_mode() -> None:
    node = ConvertVariablesToDataFrame(
        user_id="user",
        project_id="project",
        task_id="task",
        node_id="node-convert-variables-unresolved",
        input_variables={
            "title": VariableOutput(
                name="title",
                type=IO.STRING,
                value=UnresolvedValue(reason="missing"),
                var_type="user",
            ),
        },
    )

    with pytest.raises(NodeValidationError, match="unresolved value"):
        node.process()
