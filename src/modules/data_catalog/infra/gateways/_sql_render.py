"""Общий рендер SQL-шаблонов для гейтвеев каталога: таблицы запроса и column-level lineage."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core.db.ddl.parse import get_sqlglot_dialect

from src.modules.sql_template import (
    CallbackSQLExpressionEvaluator,
    SQLTemplateError,
    SQLTemplateRenderRequest,
    render_sql_template,
)
from src.node_dsl.input_expressions import evaluate_input_expression

from ...domain import SqlReferenceExtractionError

TEMPLATE_MARKERS = ("{{", "{%")


def _evaluate(expression: str, variables: Mapping[str, Any], project_variables: Mapping[str, Any]) -> Any:
    return evaluate_input_expression(
        expression=expression,
        variables=variables,
        expression_kind="single",
        expression_policy="default",
        project_variables=project_variables,
    )


def sqlglot_dialect(dialect: str) -> str:
    return get_sqlglot_dialect(dialect)


def render_sql(sql: str, dialect: str, project_variables: Mapping[str, Any]) -> tuple[str, bool]:
    """Рендерит шаблон переменными проекта; возвращает SQL и флаг «шаблон использовался».

    Бросает SqlReferenceExtractionError с префиксом `template:`, если шаблон не разрешился.
    """
    if not any(marker in sql for marker in TEMPLATE_MARKERS):
        return sql, False
    try:
        rendered = render_sql_template(
            SQLTemplateRenderRequest(
                template=sql,
                variables={},
                project_variables=project_variables,
                dialect_name=sqlglot_dialect(dialect),
                expression_evaluator=CallbackSQLExpressionEvaluator(_evaluate),
            )
        ).sql
    except (SQLTemplateError, Exception) as exc:
        raise SqlReferenceExtractionError(f"template: {exc}") from exc
    return rendered, True
