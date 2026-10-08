from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from core.db.ddl.parse import get_sqlglot_dialect

from src.modules.sql_template import (
    CallbackSQLExpressionEvaluator,
    SQLTemplateError,
    SQLTemplateRenderRequest,
    render_sql_template,
)
from src.node_dsl.input_expressions import evaluate_input_expression

from ...domain import (
    SqlReferenceExtractionError,
    SqlTableRef,
    SqlTableReferenceExtractor,
    SqlTableReferences,
)

_TEMPLATE_MARKERS = ("{{", "{%")


def _evaluate(expression: str, variables: Mapping[str, Any], project_variables: Mapping[str, Any]) -> Any:
    return evaluate_input_expression(
        expression=expression,
        variables=variables,
        expression_kind="single",
        expression_policy="default",
        project_variables=project_variables,
    )


class SqlglotTableReferenceExtractor(SqlTableReferenceExtractor):
    def extract(
        self,
        sql: str,
        dialect: str,
        project_variables: Mapping[str, Any],
    ) -> SqlTableReferences:
        used_project_variables = False
        rendered = sql
        sqlglot_dialect = get_sqlglot_dialect(dialect)
        if any(marker in sql for marker in _TEMPLATE_MARKERS):
            used_project_variables = True
            try:
                rendered = render_sql_template(
                    SQLTemplateRenderRequest(
                        template=sql,
                        variables={},
                        project_variables=project_variables,
                        dialect_name=sqlglot_dialect,
                        expression_evaluator=CallbackSQLExpressionEvaluator(_evaluate),
                    )
                ).sql
            except (SQLTemplateError, Exception) as exc:
                raise SqlReferenceExtractionError(f"template: {exc}") from exc

        try:
            statements = sqlglot.parse(rendered, read=sqlglot_dialect)
        except (SqlglotError, ValueError) as exc:
            raise SqlReferenceExtractionError(f"parse: {exc}") from exc

        tables: list[SqlTableRef] = []
        cte_names: set[str] = set()
        for statement in statements:
            if statement is None:
                continue
            for cte in statement.find_all(exp.CTE):
                alias = cte.alias
                if alias:
                    cte_names.add(alias)
            for table in statement.find_all(exp.Table):
                name = table.name
                if not name:
                    continue
                tables.append(
                    SqlTableRef(
                        table=name,
                        schema=table.db or None,
                        catalog=table.catalog or None,
                    )
                )

        return SqlTableReferences(
            tables=tuple(tables),
            cte_names=frozenset(cte_names),
            used_project_variables=used_project_variables,
        )
