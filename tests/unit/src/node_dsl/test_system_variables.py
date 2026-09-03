import pytest
from pydantic import BaseModel, Field

from src.node_dsl import BaseNode, IO, OutputField
from src.node_dsl.registry import definitions as definitions_registry
from src.node_dsl.variables import VariableOutput


class ExampleSystemVariables(BaseModel):
    target_table: str = Field(description="Target table")
    rows_written: int | None = Field(default=None, description="Rows written")


class ExampleSystemVariablesNode(BaseNode):
    TITLE = "Example System Variables Node"
    SYSTEM_VARIABLES_MODEL = ExampleSystemVariables

    output: str = OutputField()

    def process(self) -> None:
        self.output = "ok"
        self.emit_system_variables(
            ExampleSystemVariables(
                target_table="warehouse.events",
                rows_written=None,
            )
        )


class ExamplePartialSystemVariablesNode(BaseNode):
    TITLE = "Example Partial System Variables Node"
    SYSTEM_VARIABLES_MODEL = ExampleSystemVariables

    output: str = OutputField()

    def process(self) -> None:
        self.output = "ok"
        self.emit_system_variables(
            ExampleSystemVariables(
                target_table="warehouse.events",
            )
        )


def test_node_definition_exposes_system_variable_definitions():
    definition = definitions_registry._create_node_base_definition(ExampleSystemVariablesNode)
    target_table = definition.system_variable_definitions["target_table"]
    rows_written = definition.system_variable_definitions["rows_written"]

    assert target_table.type == IO.STRING
    assert target_table.required is True
    assert target_table.display_name is None
    assert target_table.description == "Target table"

    assert rows_written.type == IO.INT
    assert rows_written.required is False
    assert rows_written.display_name is None
    assert rows_written.description == "Rows written"


def test_node_definition_rejects_unsupported_system_variable_annotations():
    class UnsupportedSystemVariables(BaseModel):
        dataframe: object = Field(description="Unsupported payload")

    class UnsupportedSystemVariablesNode(BaseNode):
        TITLE = "Unsupported System Variables Node"
        SYSTEM_VARIABLES_MODEL = UnsupportedSystemVariables

        output: str = OutputField()

        def process(self) -> None:
            self.output = "ok"

    with pytest.raises(ValueError, match="Unsupported system variable annotation"):
        definitions_registry._create_node_base_definition(UnsupportedSystemVariablesNode)


def test_emit_system_variables_writes_system_scoped_variable_outputs():
    node = ExampleSystemVariablesNode(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-system-vars",
    )

    node.process()

    assert node.output_variables == {
        "target_table": VariableOutput(
            name="target_table",
            type=IO.STRING,
            value="warehouse.events",
            var_type="system",
        ),
        "rows_written": VariableOutput(
            name="rows_written",
            type=IO.INT,
            value=None,
            var_type="system",
        ),
    }


def test_emit_system_variables_skips_optional_fields_that_were_not_set():
    node = ExamplePartialSystemVariablesNode(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-system-vars-partial",
    )

    node.process()

    assert node.output_variables == {
        "target_table": VariableOutput(
            name="target_table",
            type=IO.STRING,
            value="warehouse.events",
            var_type="system",
        )
    }
