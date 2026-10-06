"""Pure checks for constant and expression values."""

import re
from typing import Any

from jinja2.exceptions import TemplateError

from src.node_dsl.input_expressions.policy import resolve_expression_policy
from src.node_dsl.input_expressions.runtime import build_environment, ensure_template_syntax_allowed
from src.schemas.node_definition import InputDefinitionModel

_PROJECT_VARIABLE_RE = re.compile(
    r"project_variables(?:\.([A-Za-z_][A-Za-z0-9_]*)|\[['\"]([^'\"]+)['\"]\])"
)


def matches_constant_type(value: Any, declared_types: set[str]) -> bool:
    if "*" in declared_types or "OBJECT" in declared_types:
        return True
    checks = {
        "STRING": lambda item: isinstance(item, str),
        "COLUMN": lambda item: isinstance(item, str),
        "COLUMN_NAME": lambda item: isinstance(item, str),
        "BOOLEAN": lambda item: isinstance(item, bool),
        "INT": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "FLOAT": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "DICT": lambda item: isinstance(item, dict),
        "JSON": lambda _item: True,
        "DATETIME": lambda item: isinstance(item, str),
        "TIMEDELTA": lambda item: (
            isinstance(item, (str, int, float)) and not isinstance(item, bool)
        ),
        "SCHEMA": lambda item: isinstance(item, dict),
        "TABLE_SCHEMA": lambda item: isinstance(item, dict),
        # Variable ports carry a name -> variable payload mapping.  An empty
        # mapping is the normal persisted default for nodes without variables.
        "VARIABLE": lambda item: isinstance(item, dict),
        "PRIMITIVE": lambda item: isinstance(item, (str, int, float, bool)),
    }
    return any(checks[name](value) for name in declared_types if name in checks)


def constant_validation_error(input_definition: InputDefinitionModel, value: Any) -> str | None:
    if value is None:
        return None if input_definition.optional else "Required constant value cannot be null."
    values = value if input_definition.is_list_type and isinstance(value, list) else [value]
    if input_definition.is_list_type and not isinstance(value, list):
        return "Input requires a list value."
    declared_types = {
        member.strip()
        for item in (
            input_definition.type
            if isinstance(input_definition.type, list)
            else [input_definition.type]
        )
        for member in str(item).upper().split(",")
    }
    for item in values:
        if not matches_constant_type(item, declared_types):
            return f"Constant value is incompatible with {sorted(declared_types)}."
        if input_definition.options is not None and item not in input_definition.options:
            return "Constant value is not one of the allowed options."
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            bounds_error = None
            if input_definition.min_value is not None and item < input_definition.min_value:
                bounds_error = f"Constant value is below minimum {input_definition.min_value}."
            elif input_definition.max_value is not None and item > input_definition.max_value:
                bounds_error = f"Constant value exceeds maximum {input_definition.max_value}."
            if bounds_error:
                return bounds_error
    return None


def graph_constant_validation_error(
    input_definition: InputDefinitionModel,
    value: Any,
    *,
    node_id: str,
    input_name: str,
    incoming_inputs: set[tuple[str, str]],
    connection_input_names: set[str],
) -> str | None:
    # A graph edge is the effective value for its target input.  Persisted
    # constants (commonly a null placeholder) must not invalidate that input.
    if input_name in connection_input_names or (node_id, input_name) in incoming_inputs:
        return None
    return constant_validation_error(input_definition, value)


def expression_validation_error(
    input_definition: InputDefinitionModel,
    *,
    expression: str,
    expression_kind: str,
    project_variable_names: set[str],
) -> str | None:
    try:
        policy = resolve_expression_policy(input_definition.expression_policy)
        environment = build_environment(policy)
        if expression_kind == "single":
            environment.compile_expression(expression, undefined_to_none=False)
        elif expression_kind == "template":
            ensure_template_syntax_allowed(expression, policy)
            environment.from_string(expression)
        else:
            return "Unsupported expression kind."
    except (TypeError, ValueError, SyntaxError, TemplateError) as exc:
        return f"Expression is invalid: {exc}"
    referenced_project_variables = {
        dot_name or bracket_name
        for dot_name, bracket_name in _PROJECT_VARIABLE_RE.findall(expression)
    }
    missing = sorted(referenced_project_variables - project_variable_names)
    if missing:
        return f"Project variables do not exist: {missing}."
    return None
