import subprocess
import sys
from datetime import datetime, timedelta

import pytest

from src.node_dsl.input_expressions import (
    ExpressionPolicy,
    ImmutableInputVariables,
    ImmutableProjectVariables,
    ImmutableVariables,
    coerce_expression_result,
    ensure_expressions_registry_initialized,
    evaluate_input_expression,
    get_default_expression_policy,
    get_expression_policy_name,
    get_registered_expression_filters,
    get_registered_expression_globals,
    get_registered_expression_tests,
    is_safe_expression_variable_name,
)
from src.node_dsl.node_typing import IO


def test_input_expressions_package_imports_in_clean_process():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import src.node_dsl.input_expressions as ie; print(ie.DEFAULT_EXPRESSION_POLICY.name)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "default"


def test_get_expression_policy_name_resolves_custom_policy():
    policy = ExpressionPolicy(
        name="restricted",
        allowed_filters=frozenset({"lower"}),
    )

    assert get_expression_policy_name(policy) == "restricted"


def test_is_safe_expression_variable_name_rejects_reserved_names():
    assert is_safe_expression_variable_name("target_table") is True
    assert is_safe_expression_variable_name("input_variables") is False
    assert is_safe_expression_variable_name("for") is False


def test_immutable_input_variables_freezes_nested_payloads():
    variables = ImmutableInputVariables({"nested": {"key": "value"}, "items": [1, 2]})

    assert variables.nested["key"] == "value"
    assert variables["items"] == (1, 2)

    with pytest.raises(TypeError):
        variables.nested["key"] = "other"


def test_immutable_variable_types_share_mapping_behavior_without_losing_scope():
    input_variables = ImmutableInputVariables({"sample": "input"})
    project_variables = ImmutableProjectVariables({"sample": "project"})

    assert isinstance(input_variables, ImmutableVariables)
    assert isinstance(project_variables, ImmutableVariables)
    assert not isinstance(project_variables, ImmutableInputVariables)
    assert input_variables.sample == input_variables["sample"] == "input"
    assert project_variables.sample == project_variables["sample"] == "project"


def test_immutable_input_variables_support_list_concatenation_with_literals():
    result = evaluate_input_expression(
        expression="input_variables['items'] + [3]",
        variables={"items": [1, 2]},
        expression_kind="single",
        expression_policy="default",
    )

    assert result == (1, 2, 3)


def test_evaluate_input_expression_supports_single_expression():
    result = evaluate_input_expression(
        expression="input_variables['base'] + 2",
        variables={"base": 40},
        expression_kind="single",
        expression_policy="default",
    )

    assert result == 42


def test_evaluate_input_expression_supports_template_expression():
    result = evaluate_input_expression(
        expression="SELECT * FROM {{ input_variables.target_table }}",
        variables={"target_table": "analytics.events"},
        expression_kind="template",
        expression_policy="default",
    )

    assert result == "SELECT * FROM analytics.events"


def test_default_policy_allows_registered_system_attribute():
    variables = {"__dvt_error_text": "upstream failed"}

    assert evaluate_input_expression(
        expression="input_variables.__dvt_error_text",
        variables=variables,
        expression_kind="single",
        expression_policy="default",
    ) == "upstream failed"
    assert evaluate_input_expression(
        expression="{{ input_variables.__dvt_error_text }}",
        variables=variables,
        expression_kind="template",
        expression_policy="default",
    ) == "upstream failed"


@pytest.mark.parametrize(
    ("expression", "expression_kind"),
    [
        ("input_variables.__dvt_error_text", "single"),
        ("{{ input_variables.__dvt_error_text }}", "template"),
    ],
)
def test_attribute_rule_must_be_enabled_by_policy(expression, expression_kind):
    policy = ExpressionPolicy(
        name="no-system-attributes",
        allowed_filters=frozenset(),
    )

    with pytest.raises(ValueError, match=r"Unsafe expression access.*__dvt_error_text"):
        evaluate_input_expression(
            expression=expression,
            variables={"__dvt_error_text": "upstream failed"},
            expression_kind=expression_kind,
            expression_policy=policy,
        )


def test_registered_attribute_rule_is_scoped_to_owner_type():
    class Payload:
        pass

    payload = Payload()
    setattr(payload, "__dvt_error_text", "not a system variable container")

    with pytest.raises(ValueError, match=r"Unsafe expression access.*__dvt_error_text"):
        evaluate_input_expression(
            expression="input_variables.payload.__dvt_error_text",
            variables={"payload": payload},
            expression_kind="single",
            expression_policy="default",
        )


def test_evaluate_input_expression_rejects_missing_variable():
    with pytest.raises(ValueError, match="Variable 'missing_key' not found"):
        evaluate_input_expression(
            expression="missing_key",
            variables={},
            expression_kind="single",
            expression_policy="default",
        )


def test_evaluate_input_expression_rejects_template_statements():
    with pytest.raises(ValueError, match="statement blocks"):
        evaluate_input_expression(
            expression="{% for item in input_variables['items'] %}{{ item }}{% endfor %}",
            variables={"items": [1, 2]},
            expression_kind="template",
            expression_policy="default",
        )


def test_registry_accessors_return_initialized_defaults():
    ensure_expressions_registry_initialized()

    filters = {item.name for item in get_registered_expression_filters()}
    tests = {item.name for item in get_registered_expression_tests()}
    globals_ = {item.name for item in get_registered_expression_globals()}
    policy = get_default_expression_policy()

    assert {"lower", "tojson"}.issubset(filters)
    assert "odd" in tests
    assert {"len", "now"}.issubset(globals_)
    assert "lower" in policy.allowed_filters
    assert "odd" in policy.allowed_tests
    assert "len" in policy.allowed_globals


def test_registry_initialization_is_idempotent():
    ensure_expressions_registry_initialized()
    ensure_expressions_registry_initialized()

    assert any(item.name == "lower" for item in get_registered_expression_filters())


def test_evaluate_input_expression_supports_registered_globals_tests_and_filters():
    assert evaluate_input_expression(
        expression="len([1, 2, 3])",
        variables={},
        expression_kind="single",
        expression_policy="default",
    ) == 3

    assert evaluate_input_expression(
        expression="{{ 1 is odd }}",
        variables={},
        expression_kind="template",
        expression_policy="default",
    ) is True

    assert evaluate_input_expression(
        expression="{{ 'ABC' | lower }}",
        variables={},
        expression_kind="template",
        expression_policy="default",
    ) == "abc"


def test_coerce_expression_result_supports_datetime_and_timedelta():
    resolved_datetime = coerce_expression_result("2026-03-31T12:30:45", IO.DATETIME)
    resolved_timedelta = coerce_expression_result("1d 2h 3m 4s", IO.TIMEDELTA)

    assert resolved_datetime == datetime(2026, 3, 31, 12, 30, 45)
    assert resolved_timedelta == timedelta(days=1, hours=2, minutes=3, seconds=4)


def test_coerce_expression_result_rejects_boolean_for_int():
    with pytest.raises(ValueError, match="must not be boolean"):
        coerce_expression_result(True, IO.INT)


def test_coerce_expression_result_allows_none_when_requested():
    assert coerce_expression_result(None, IO.INT, allow_none=True) is None
