import pytest

from src.node_dsl import IO
from src.node_dsl.variables import (
    UnresolvedValue,
    VariableOutput,
    build_variable_output,
)
from src.nodes.primitive.create_variable import CreateVariable
from src.nodes.primitive.manage_variables import ManageVariables


def test_create_variable_emits_user_scoped_variable_output():
    node = CreateVariable(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-create-variable",
        name="message",
        type=IO.STRING,
        value="hello",
    )

    node.process()

    assert node.output_variables == {
        "message": VariableOutput(name="message", type=IO.STRING, value="hello", var_type="user"),
    }


def test_create_variable_resolves_linked_variable_reference():
    node = CreateVariable(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-create-variable",
        name="limit_copy",
        type=IO.INT,
        value={"__dvt_type": "expr", "value": "limit", "expression_kind": "single"},
        input_variables={
            "limit": VariableOutput(name="limit", type=IO.INT, value=10, var_type="user"),
        },
    )

    node.process()

    assert node.output_variables["limit_copy"] == VariableOutput(
        name="limit_copy",
        type=IO.INT,
        value=10,
        var_type="user",
    )


def test_create_variable_resolves_expression_value():
    node = CreateVariable(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-create-variable",
        name="limit_plus_one",
        type=IO.INT,
        value={
            "__dvt_type": "expr",
            "value": "input_variables.base_limit + 1",
            "expression_kind": "single",
        },
        input_variables={
            "base_limit": VariableOutput(name="base_limit", type=IO.INT, value=41, var_type="user"),
        },
    )

    node.process()

    assert node.output_variables["limit_plus_one"] == VariableOutput(
        name="limit_plus_one",
        type=IO.INT,
        value=42,
        var_type="user",
    )


def test_create_variable_emits_list_variable_output() -> None:
    node = CreateVariable(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-create-variable-list",
        name="numbers",
        type=IO.INT,
        is_list_type=True,
        value=[1, "2", 3],
    )

    node.process()

    assert node.output_variables["numbers"] == VariableOutput(
        name="numbers",
        type=IO.INT,
        value=[1, 2, 3],
        var_type="user",
        is_list_type=True,
    )


def test_create_variable_process_metadata_emits_unresolved_value_for_list_template_expression() -> None:
    node = CreateVariable(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-create-variable-list-metadata",
        name="numbers",
        type=IO.INT,
        is_list_type=True,
        value={
            "__dvt_type": "expr",
            "value": "{{ [1, 2] }}",
            "expression_kind": "template",
        },
    )

    node.process_metadata()

    assert isinstance(node.output_variables["numbers"].value, UnresolvedValue)
    assert node.output_variables["numbers"].is_list_type is True
    assert node.output_variables["numbers"].value.is_list_type is True


def test_create_variable_process_metadata_emits_unresolved_value_for_json_expression() -> None:
    node = CreateVariable(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-create-variable",
        name="payload",
        type=IO.JSON,
        value={
            "__dvt_type": "expr",
            "value": "{'a': 1}",
            "expression_kind": "single",
        },
    )

    node.process_metadata()

    assert node.output_variables["payload"].type == IO.JSON


def test_create_variable_keeps_none_when_nullable() -> None:
    node = CreateVariable(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-create-variable",
        name="maybe_name",
        type=IO.STRING,
        value={"__dvt_type": "expr", "value": "name_value", "expression_kind": "single"},
        nullable=True,
        input_variables={
            "name_value": VariableOutput(name="name_value", type=IO.STRING, value=None, var_type="user"),
        },
    )

    node.process()

    assert node.output_variables["maybe_name"] == VariableOutput(
        name="maybe_name",
        type=IO.STRING,
        value=None,
        var_type="user",
    )


def test_create_variable_rejects_non_literal_default() -> None:
    node = CreateVariable(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-create-variable",
        name="broken_default",
        type=IO.STRING,
        value=None,
        default={"__dvt_type": "expr", "value": "x", "expression_kind": "single"},
    )

    with pytest.raises(ValueError, match="`default` must be a literal value"):
        node.process()


def test_manage_variables_merges_defined_variables_into_output_variables():
    node = ManageVariables(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-manage-variables",
        input_variables={
            "existing": VariableOutput(name="existing", type=IO.INT, value=1, var_type="user"),
            "base_limit": VariableOutput(name="base_limit", type=IO.INT, value=10, var_type="user"),
        },
        defined_variables={
            "existing": {"type": IO.INT, "value": 2},
            "copied": {
                "type": IO.INT,
                "value_input": {"__dvt_type": "expr", "value": "existing", "expression_kind": "single"},
            },
            "calculated": {
                "type": IO.INT,
                "value_input": {
                    "__dvt_type": "expr",
                    "value": "input_variables.base_limit + 5",
                    "expression_kind": "single",
                },
            },
        },
    )

    node.process()

    assert node.output_variables == {
        "existing": VariableOutput(name="existing", type=IO.INT, value=2, var_type="user"),
        "base_limit": VariableOutput(name="base_limit", type=IO.INT, value=10, var_type="user"),
        "copied": VariableOutput(name="copied", type=IO.INT, value=1, var_type="user"),
        "calculated": VariableOutput(name="calculated", type=IO.INT, value=15, var_type="user"),
    }


def test_manage_variables_rejects_payload_with_both_literal_and_input():
    node = ManageVariables(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-manage-variables",
        defined_variables={
            "broken": {
                "type": IO.STRING,
                "value": "x",
                "value_input": {"__dvt_type": "expr", "value": "source", "expression_kind": "single"},
            },
        },
    )

    with pytest.raises(ValueError, match="exactly one of 'value' or 'value_input'"):
        node.process()


def test_manage_variables_process_metadata_keeps_typed_outputs_for_unresolved_expression() -> None:
    node = ManageVariables(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-manage-variables",
        input_variables={
            "base_limit": VariableOutput(name="base_limit", type=IO.INT, value=10, var_type="user"),
        },
        defined_variables={
            "title": {
                "type": IO.STRING,
                "value_input": {
                    "__dvt_type": "expr",
                    "value": "missing_name",
                    "expression_kind": "single",
                },
            },
            "copied": {
                "type": IO.INT,
                "value_input": {
                    "__dvt_type": "expr",
                    "value": "input_variables.base_limit + 5",
                    "expression_kind": "single",
                },
            },
        },
    )

    node.process_metadata()

    assert isinstance(node.output_variables["title"].value, UnresolvedValue)
    assert node.output_variables["title"].type == IO.STRING
    assert node.output_variables["copied"].value == 15


def test_manage_variables_supports_list_variables() -> None:
    node = ManageVariables(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-manage-variables-list",
        input_variables={
            "existing": VariableOutput(name="existing", type=IO.INT, value=[1], var_type="user", is_list_type=True),
        },
        defined_variables={
            "existing": {"type": IO.INT, "is_list_type": True, "value": [2, "3"]},
            "copied": {
                "type": IO.INT,
                "is_list_type": True,
                "value_input": {
                    "__dvt_type": "expr",
                    "value": "input_variables.existing + [4]",
                    "expression_kind": "single",
                },
            },
        },
    )

    node.process()

    assert node.output_variables["existing"] == VariableOutput(
        name="existing",
        type=IO.INT,
        value=[2, 3],
        var_type="user",
        is_list_type=True,
    )
    assert node.output_variables["copied"] == VariableOutput(
        name="copied",
        type=IO.INT,
        value=[1, 4],
        var_type="user",
        is_list_type=True,
    )


def test_manage_variables_apply_default_and_nullable_policy() -> None:
    node = ManageVariables(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-manage-variables",
        input_variables={
            "raw_limit": VariableOutput(name="raw_limit", type=IO.INT, value=None, var_type="user"),
            "raw_name": VariableOutput(name="raw_name", type=IO.STRING, value=None, var_type="user"),
        },
        defined_variables={
            "limit_with_default": {
                "type": IO.INT,
                "value_input": {
                    "__dvt_type": "expr",
                    "value": "raw_limit",
                    "expression_kind": "single",
                },
                "default": 5,
            },
            "nullable_name": {
                "type": IO.STRING,
                "value_input": {
                    "__dvt_type": "expr",
                    "value": "raw_name",
                    "expression_kind": "single",
                },
                "nullable": True,
            },
        },
    )

    node.process()

    assert node.output_variables["limit_with_default"] == VariableOutput(
        name="limit_with_default",
        type=IO.INT,
        value=5,
        var_type="user",
    )
    assert node.output_variables["nullable_name"] == VariableOutput(
        name="nullable_name",
        type=IO.STRING,
        value=None,
        var_type="user",
    )


def test_manage_variables_rejects_non_literal_default() -> None:
    node = ManageVariables(
        user_id="user-1",
        project_id="project-1",
        task_id="task-1",
        node_id="node-manage-variables",
        defined_variables={
            "broken": {
                "type": IO.STRING,
                "value": None,
                "default": {"__dvt_type": "expr", "value": "x", "expression_kind": "single"},
            },
        },
    )

    with pytest.raises(ValueError, match="`default` must be a literal value"):
        node.process()


def test_build_variable_output_preserves_system_var_type():
    variable_output = build_variable_output(
        "target_table",
        {"type": IO.STRING, "value": "warehouse.events", "var_type": "system"},
    )

    assert variable_output == VariableOutput(
        name="target_table",
        type=IO.STRING,
        value="warehouse.events",
        var_type="system",
    )
