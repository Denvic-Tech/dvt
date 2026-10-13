from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.node_dsl.input_expressions import evaluate_input_expression
from src.node_dsl.variables import is_unresolved_value

from ...domain import ExpressionResolver, ExpressionUnresolvedError


class NodeDslExpressionResolver(ExpressionResolver):
    """Статический резолв expression-входов переменными проекта (без input-переменных рантайма)."""

    def resolve(
        self,
        expression: str,
        expression_kind: str,
        project_variables: Mapping[str, Any],
    ) -> Any:
        try:
            result = evaluate_input_expression(
                expression=expression,
                variables={},
                expression_kind=expression_kind or "template",
                expression_policy="default",
                project_variables=project_variables,
            )
        except Exception as exc:
            raise ExpressionUnresolvedError(f"{expression!r}: {exc}") from exc
        if is_unresolved_value(result):
            raise ExpressionUnresolvedError(f"{expression!r} depends on runtime values")
        return result
