from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


class SQLTemplateInterpolationContext(StrEnum):
    LITERAL = "literal"
    IDENTIFIER = "identifier"
    QUOTED_LITERAL_CONTENT = "quoted_literal_content"


class SQLExpressionEvaluator(Protocol):
    def evaluate(
        self,
        expression: str,
        *,
        variables: Mapping[str, Any],
        project_variables: Mapping[str, Any],
    ) -> Any: ...


@dataclass(frozen=True)
class SQLTemplateRenderRequest:
    template: str
    variables: Mapping[str, Any]
    project_variables: Mapping[str, Any]
    dialect_name: str | None
    expression_evaluator: SQLExpressionEvaluator


@dataclass(frozen=True)
class SQLTemplateRenderResult:
    sql: str
