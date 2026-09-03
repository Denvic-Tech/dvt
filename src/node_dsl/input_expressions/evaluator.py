from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from jinja2.exceptions import SecurityError, UndefinedError
from jinja2.runtime import Undefined

from .policy import (
    is_safe_expression_variable_name,
    resolve_expression_policy,
)
from .runtime import (
    ImmutableInputVariables,
    ImmutableProjectVariables,
    build_environment,
    ensure_template_syntax_allowed,
)
from .types import ExpressionPolicyRef

_UNDEFINED_NAME_RE = re.compile(r"^'(?P<name>[^']+)' is undefined$")


def _raise_undefined_error(undefined: Undefined) -> None:
    message = undefined._undefined_message
    exception_type = undefined._undefined_exception
    if exception_type is SecurityError:
        raise ValueError(f"Unsafe expression access: {message}")

    match = _UNDEFINED_NAME_RE.match(message)
    if match is not None:
        raise ValueError(f"Variable '{match.group('name')}' not found.")
    raise ValueError(message)


def evaluate_input_expression(
    *,
    expression: str,
    variables: Mapping[str, Any] | None,
    expression_kind: str,
    expression_policy: ExpressionPolicyRef = None,
    project_variables: Mapping[str, Any] | None = None,
) -> Any:
    policy = resolve_expression_policy(expression_policy)
    environment = build_environment(policy)
    frozen_variables = ImmutableInputVariables(variables)
    frozen_project_variables = ImmutableProjectVariables(project_variables)
    context = {
        "input_variables": frozen_variables,
        "project_variables": frozen_project_variables,
    }
    context.update(
        {
            key: value
            for key, value in frozen_project_variables.items()
            if key != "input_variables" and is_safe_expression_variable_name(key)
        }
    )
    context.update(
        {
            key: value
            for key, value in frozen_variables.items()
            if key != "project_variables" and is_safe_expression_variable_name(key)
        }
    )

    if expression_kind == "single":
        compiled_expression = environment.compile_expression(expression, undefined_to_none=False)
        try:
            result = compiled_expression(**context)
        except SecurityError as err:
            raise ValueError(f"Unsafe expression access: {err}") from err
        except UndefinedError as err:
            match = _UNDEFINED_NAME_RE.match(str(err))
            if match is not None:
                raise ValueError(f"Variable '{match.group('name')}' not found.") from err
            raise ValueError(str(err)) from err
        if isinstance(result, Undefined):
            _raise_undefined_error(result)
        return result

    if expression_kind == "template":
        ensure_template_syntax_allowed(expression, policy)
        template = environment.from_string(expression)
        try:
            result = template.render(**context)
        except SecurityError as err:
            raise ValueError(f"Unsafe expression access: {err}") from err
        except UndefinedError as err:
            match = _UNDEFINED_NAME_RE.match(str(err))
            if match is not None:
                raise ValueError(f"Variable '{match.group('name')}' not found.") from err
            raise ValueError(str(err)) from err
        if isinstance(result, Undefined):
            _raise_undefined_error(result)
        return result

    raise ValueError(f"Unsupported expression kind '{expression_kind}'.")
