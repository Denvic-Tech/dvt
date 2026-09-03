from datetime import datetime, timedelta

import pytest

from src.node_dsl.core.input_values import (
    NodeInputConstantValue,
    NodeInputExpressionValue,
    NodeInputLinkValue,
    iter_node_input_link_values,
    parse_node_input_value,
    parse_node_runtime_input_value,
    resolve_node_input_value,
)
from src.node_dsl.input_expressions import ExpressionPolicy
from src.node_dsl.node_typing import IO
from src.node_dsl.variables import VariableOutput


def test_parse_input_value_supports_structured_dicts():
    parsed_const = parse_node_input_value({"__dvt_type": "const", "value": 123})
    parsed_expr = parse_node_input_value(
        {
            "__dvt_type": "expr",
            "value": "SELECT * FROM {{ input_variables.target_table }}",
            "expression_kind": "template",
        }
    )
    parsed_link = parse_node_input_value(
        {"__dvt_type": "link", "node_id": "source", "output_name": "out"}
    )

    assert isinstance(parsed_const, NodeInputConstantValue)
    assert parsed_const.value == 123

    assert isinstance(parsed_expr, NodeInputExpressionValue)
    assert parsed_expr.expression_kind == "template"

    assert isinstance(parsed_link, NodeInputLinkValue)
    assert parsed_link.node_id == "source"
    assert parsed_link.output_name == "out"


def test_resolve_input_value_supports_const():
    resolved_const = resolve_node_input_value({"__dvt_type": "const", "value": "x"})

    assert resolved_const == "x"


def test_resolve_input_value_supports_single_expression_and_coerces_target_type():
    resolved_expr = resolve_node_input_value(
        {
            "__dvt_type": "expr",
            "value": "input_variables['base'] + 2",
            "expression_kind": "single",
        },
        variables={"base": 40},
        target_type=IO.INT,
        allow_expressions=True,
        expression_policy="default",
    )

    assert resolved_expr == 42


def test_resolve_input_value_supports_list_expression_and_coerces_items():
    resolved_expr = resolve_node_input_value(
        {
            "__dvt_type": "expr",
            "value": "partition_columns",
            "expression_kind": "single",
        },
        variables={"partition_columns": ["country", "date"]},
        target_type=IO.STRING,
        is_list_type=True,
        allow_expressions=True,
        expression_policy="default",
    )

    assert resolved_expr == ["country", "date"]


def test_resolve_input_value_rejects_scalar_for_list_expression():
    with pytest.raises(ValueError, match="list-like value"):
        resolve_node_input_value(
            {
                "__dvt_type": "expr",
                "value": "partition_columns",
                "expression_kind": "single",
            },
            variables={"partition_columns": "country"},
            target_type=IO.STRING,
            is_list_type=True,
            allow_expressions=True,
            expression_policy="default",
        )


def test_resolve_input_value_supports_bare_variable_reference():
    resolved_expr = resolve_node_input_value(
        {
            "__dvt_type": "expr",
            "value": "cfg_key",
            "expression_kind": "single",
        },
        variables={"cfg_key": "cfg_value"},
    )

    assert resolved_expr == "cfg_value"


def test_resolve_input_value_keeps_input_and_project_variable_namespaces_separate():
    value = {
        "__dvt_type": "expr",
        "value": "[input_variables.message, project_variables.message, message]",
        "expression_kind": "single",
    }

    resolved = resolve_node_input_value(
        value,
        variables={"message": "from-input"},
        project_variables={"message": "from-project"},
    )

    assert resolved == ["from-input", "from-project", "from-input"]


def test_resolve_input_value_uses_project_variable_for_bare_name_when_input_is_missing():
    resolved = resolve_node_input_value(
        {
            "__dvt_type": "expr",
            "value": "message",
            "expression_kind": "single",
        },
        variables={},
        project_variables={"message": "from-project"},
    )

    assert resolved == "from-project"


def test_resolve_input_value_supports_namespaced_variables_inside_json_array_template():
    resolved = resolve_node_input_value(
        {
            "__dvt_type": "expr",
            "value": '["{{ input_variables.input_value }}", "{{ project_variables.project_value }}"]',
            "expression_kind": "template",
        },
        variables={"input_value": "input"},
        project_variables={"project_value": "project"},
        target_type=IO.SCHEMA,
    )

    assert resolved == ["input", "project"]


def test_resolve_input_value_treats_quoted_identifier_as_string_literal():
    resolved_expr = resolve_node_input_value(
        {
            "__dvt_type": "expr",
            "value": '"cfg_key"',
            "expression_kind": "single",
        },
        variables={"cfg_key": "cfg_value"},
    )

    assert resolved_expr == "cfg_key"


def test_resolve_input_value_supports_template_expression_for_strings():
    resolved_expr = resolve_node_input_value(
        {
            "__dvt_type": "expr",
            "value": "SELECT * FROM {{ input_variables.target_table }}",
            "expression_kind": "template",
        },
        variables={"target_table": "analytics.events"},
        target_type=IO.STRING,
        allow_expressions=True,
        expression_policy="default",
    )

    assert resolved_expr == "SELECT * FROM analytics.events"


def test_resolve_input_value_supports_datetime_expression_result():
    resolved_expr = resolve_node_input_value(
        {
            "__dvt_type": "expr",
            "value": "run_at",
            "expression_kind": "single",
        },
        variables={"run_at": "2026-03-31T12:30:45"},
        target_type=IO.DATETIME,
        allow_expressions=True,
        expression_policy="default",
    )

    assert resolved_expr == datetime(2026, 3, 31, 12, 30, 45)


def test_resolve_input_value_supports_timedelta_expression_result():
    resolved_expr = resolve_node_input_value(
        {
            "__dvt_type": "expr",
            "value": "time_to_add",
            "expression_kind": "single",
        },
        variables={"time_to_add": "1d 2h 3m 4s"},
        target_type=IO.TIMEDELTA,
        allow_expressions=True,
        expression_policy="default",
    )

    assert resolved_expr == timedelta(days=1, hours=2, minutes=3, seconds=4)


def test_resolve_input_value_allows_none_for_expression_when_requested():
    resolved_expr = resolve_node_input_value(
        {
            "__dvt_type": "expr",
            "value": "maybe_limit",
            "expression_kind": "single",
        },
        variables={"maybe_limit": None},
        target_type=IO.INT,
        allow_expressions=True,
        expression_policy="default",
        allow_none=True,
    )

    assert resolved_expr is None


def test_resolve_input_value_raises_on_missing_variable():
    with pytest.raises(Exception, match="missing"):
        resolve_node_input_value(
            {"__dvt_type": "expr", "value": "missing", "expression_kind": "single"},
            variables={},
        )


def test_resolve_input_value_unwraps_variable_output_object():
    resolved = resolve_node_input_value(
        {"__dvt_type": "expr", "value": "cfg_key", "expression_kind": "single"},
        variables={
            "cfg_key": VariableOutput(name="cfg_key", type=IO.STRING, value="from_create_variable"),
        },
    )

    assert resolved == "from_create_variable"


def test_resolve_input_value_rejects_expression_when_input_does_not_allow_it():
    with pytest.raises(ValueError, match="Expressions are not enabled"):
        resolve_node_input_value(
            {
                "__dvt_type": "expr",
                "value": "cfg_key",
                "expression_kind": "single",
            },
            variables={"cfg_key": "cfg_value"},
            allow_expressions=False,
        )


def test_resolve_input_value_rejects_template_statements():
    with pytest.raises(ValueError, match="statement blocks"):
        resolve_node_input_value(
            {
                "__dvt_type": "expr",
                "value": "{% for item in input_variables['items'] %}{{ item }}{% endfor %}",
                "expression_kind": "template",
            },
            variables={"items": [1, 2]},
            target_type=IO.STRING,
            allow_expressions=True,
            expression_policy="default",
        )


def test_resolve_input_value_accepts_custom_expression_policy_object():
    resolved_expr = resolve_node_input_value(
        {
            "__dvt_type": "expr",
            "value": "input_variables['cfg_key'] | lower",
            "expression_kind": "single",
        },
        variables={"cfg_key": "CFG_VALUE"},
        target_type=IO.STRING,
        allow_expressions=True,
        expression_policy=ExpressionPolicy(
            name="lower-only",
            allowed_filters=frozenset({"lower"}),
        ),
    )

    assert resolved_expr == "cfg_value"


def test_resolve_input_value_reserved_name_stays_reserved_literal():
    resolved_expr = resolve_node_input_value(
        {
            "__dvt_type": "expr",
            "value": "len",
            "expression_kind": "single",
        },
        variables={"len": "shadowed"},
    )

    assert callable(resolved_expr)


def test_resolve_input_value_supports_explicit_reference_for_unsafe_name():
    resolved_expr = resolve_node_input_value(
        {
            "__dvt_type": "expr",
            "value": 'input_variables["target-table"]',
            "expression_kind": "single",
        },
        variables={"target-table": "analytics.events"},
    )

    assert resolved_expr == "analytics.events"


def test_iter_node_input_link_values_supports_single_and_list():
    single = list(
        iter_node_input_link_values(
            {"__dvt_type": "link", "node_id": "single", "output_name": "o"}
        )
    )
    multi = list(
        iter_node_input_link_values(
            [
                {"__dvt_type": "link", "node_id": "a", "output_name": "x"},
                {"__dvt_type": "link", "node_id": "b", "output_name": "y"},
            ]
        )
    )

    assert len(single) == 1
    assert single[0].node_id == "single"
    assert [(item.node_id, item.output_name) for item in multi] == [("a", "x"), ("b", "y")]


def test_parse_input_value_rejects_dvt_type_without_alias():
    assert parse_node_input_value({"dvt_type": "const", "value": 123}) is None


def test_parse_input_value_rejects_legacy_var_payload():
    with pytest.raises(ValueError, match="Unknown dvt_type 'var'"):
        parse_node_input_value({"__dvt_type": "var", "name": "my_var"})


def test_parse_input_value_requires_expression_kind_for_expr_payload():
    with pytest.raises(Exception, match="expression_kind"):
        parse_node_input_value(
            {
                "__dvt_type": "expr",
                "value": "input_variables['x']",
            }
        )


def test_parse_runtime_input_value_rejects_legacy_type_wrapper():
    assert parse_node_runtime_input_value({"type": "CONSTANT", "value": 123}) is None


def test_parse_runtime_input_value_rejects_link_without_alias():
    assert parse_node_runtime_input_value({"node_id": "source", "output_name": "out"}) is None
