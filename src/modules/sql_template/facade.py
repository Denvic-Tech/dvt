from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .domain import SQLExpressionEvaluator, SQLTemplateRenderRequest, SQLTemplateRenderResult
from .flow import RenderSQLTemplateUseCase, SQLTemplateProvider
from .infra import (
    JinjaInterpolationTokenizer,
    SQLGlotContextClassifier,
    SQLIdentifierSerializer,
    SQLLiteralSerializer,
)


class CallbackSQLExpressionEvaluator(SQLExpressionEvaluator):
    def __init__(self, callback: Callable[[str, Mapping[str, Any], Mapping[str, Any]], Any]) -> None:
        self._callback = callback

    def evaluate(self, expression: str, *, variables, project_variables) -> Any:
        return self._callback(expression, variables, project_variables)


def build_render_sql_template_use_case() -> RenderSQLTemplateUseCase:
    return SQLTemplateProvider(
        tokenizer=JinjaInterpolationTokenizer(),
        context_classifier=SQLGlotContextClassifier(),
        literal_serializer=SQLLiteralSerializer(),
        identifier_serializer=SQLIdentifierSerializer(),
    ).create_render_sql_template_use_case()


def render_sql_template(request: SQLTemplateRenderRequest) -> SQLTemplateRenderResult:
    return build_render_sql_template_use_case().execute(request)
