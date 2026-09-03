from src.node_dsl import IO
from src.node_dsl.variables import (
    UnresolvedValue,
    VariableOutput,
    build_variable_map_metadata,
    is_unresolved_value,
    make_unresolved_value,
)


def test_make_unresolved_value_marks_value_and_preserves_declared_type() -> None:
    value = make_unresolved_value(reason="missing upstream data", declared_type=IO.STRING)

    assert is_unresolved_value(value) is True
    assert value.kind == "UNRESOLVED"
    assert value.reason == "missing upstream data"
    assert value.declared_type == "STRING"


def test_make_unresolved_value_preserves_list_flag() -> None:
    value = make_unresolved_value(
        reason="missing upstream data",
        declared_type=IO.INT,
        is_list_type=True,
    )

    assert value.is_list_type is True


def test_build_variable_map_metadata_marks_unresolved_descriptors() -> None:
    metadata = build_variable_map_metadata(
        {
            "resolved_name": VariableOutput(name="resolved_name", type=IO.INT, value=10, var_type="user"),
            "pending_name": VariableOutput(
                name="pending_name",
                type=IO.STRING,
                value=UnresolvedValue(reason="metadata-mode", declared_type="STRING", is_list_type=True),
                var_type="system",
                is_list_type=True,
            ),
        }
    )

    assert metadata.type == "VARIABLE_MAP"
    assert [item.name for item in metadata.variables] == ["pending_name", "resolved_name"]
    assert metadata.variables[0].value_state == "unresolved"
    assert metadata.variables[0].var_type == "system"
    assert metadata.variables[0].is_list_type is True
    assert metadata.variables[1].value_state == "resolved"
    assert metadata.variables[1].is_list_type is False
