from datetime import datetime, timedelta

import pytest

from src.node_dsl import IO
from src.node_dsl.variables import (
    VariableOutput,
    build_variable_output,
    coerce_variable_value,
    resolve_literal_input_value,
    resolve_variable_runtime_value,
)
from src.node_dsl.variables.type_system import parse_human_timedelta, coerce_timedelta_value


def test_parse_human_timedelta_supports_compound_values():
    assert parse_human_timedelta("1d 2h 3m 4s") == timedelta(days=1, hours=2, minutes=3, seconds=4)


def test_coerce_timedelta_value_supports_human_readable_string():
    assert coerce_timedelta_value("2h 15m") == timedelta(hours=2, minutes=15)


def test_coerce_variable_value_supports_datetime_values():
    assert coerce_variable_value("2026-04-01T10:20:30", IO.DATETIME) == datetime(2026, 4, 1, 10, 20, 30)


def test_coerce_variable_value_rejects_bool_for_int():
    with pytest.raises(ValueError, match="INT variable value must not be boolean"):
        coerce_variable_value(True, IO.INT)


def test_coerce_variable_value_allows_none_when_requested():
    assert coerce_variable_value(None, IO.STRING, allow_none=True) is None


def test_coerce_variable_value_supports_lists_for_supported_scalar_types():
    assert coerce_variable_value([1, "2", 3], IO.INT, is_list_type=True) == [1, 2, 3]


def test_coerce_variable_value_rejects_null_items_in_list():
    with pytest.raises(ValueError, match="items cannot be null"):
        coerce_variable_value([1, None], IO.INT, is_list_type=True)


def test_build_variable_output_validates_name_and_scope():
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


def test_resolve_variable_runtime_value_resolves_expression():
    resolved = resolve_variable_runtime_value(
        {"__dvt_type": "expr", "value": "input_variables.base_limit + 1", "expression_kind": "single"},
        variables={
            "base_limit": VariableOutput(name="base_limit", type=IO.INT, value=41),
        },
        variable_type=IO.INT,
    )

    assert resolved == 42


def test_resolve_variable_runtime_value_resolves_list_expression():
    resolved = resolve_variable_runtime_value(
        {"__dvt_type": "expr", "value": "[input_variables.base_limit, 5]", "expression_kind": "single"},
        variables={
            "base_limit": VariableOutput(name="base_limit", type=IO.INT, value=41),
        },
        variable_type=IO.INT,
        is_list_type=True,
    )

    assert resolved == [41, 5]


def test_resolve_variable_runtime_value_rejects_template_expression_for_list():
    with pytest.raises(ValueError, match="List variables support only single expressions"):
        resolve_variable_runtime_value(
            {"__dvt_type": "expr", "value": "{{ [1, 2] }}", "expression_kind": "template"},
            variables=None,
            variable_type=IO.INT,
            is_list_type=True,
        )


def test_resolve_variable_runtime_value_rejects_link_payload():
    with pytest.raises(ValueError, match="Variable links are not supported"):
        resolve_variable_runtime_value(
            {"__dvt_type": "link", "node_id": "source", "output_name": "output_variables"},
            variables=None,
            variable_type=IO.STRING,
        )


def test_resolve_literal_input_value_rejects_expression_payload():
    with pytest.raises(ValueError, match="`default` must be a literal value"):
        resolve_literal_input_value(
            {"__dvt_type": "expr", "value": "x", "expression_kind": "single"},
            field_name="default",
        )


def test_resolve_variable_runtime_value_uses_default_when_expression_returns_none():
    resolved = resolve_variable_runtime_value(
        {"__dvt_type": "expr", "value": "maybe_number", "expression_kind": "single"},
        variables={"maybe_number": VariableOutput(name="maybe_number", type=IO.INT, value=None)},
        variable_type=IO.INT,
        default_value=7,
        default_is_set=True,
    )

    assert resolved == 7


def test_resolve_variable_runtime_value_keeps_none_when_nullable():
    resolved = resolve_variable_runtime_value(
        {"__dvt_type": "expr", "value": "maybe_name", "expression_kind": "single"},
        variables={"maybe_name": VariableOutput(name="maybe_name", type=IO.STRING, value=None)},
        variable_type=IO.STRING,
        nullable=True,
    )

    assert resolved is None


def test_resolve_variable_runtime_value_uses_list_default_when_expression_returns_none():
    resolved = resolve_variable_runtime_value(
        {"__dvt_type": "expr", "value": "maybe_numbers", "expression_kind": "single"},
        variables={"maybe_numbers": VariableOutput(name="maybe_numbers", type=IO.INT, value=None)},
        variable_type=IO.INT,
        is_list_type=True,
        default_value=[7, 8],
        default_is_set=True,
    )

    assert resolved == [7, 8]


def test_resolve_variable_runtime_value_rejects_none_without_policy():
    with pytest.raises(ValueError, match="cannot be null"):
        resolve_variable_runtime_value(
            {"__dvt_type": "expr", "value": "maybe_name", "expression_kind": "single"},
            variables={"maybe_name": VariableOutput(name="maybe_name", type=IO.STRING, value=None)},
            variable_type=IO.STRING,
        )
