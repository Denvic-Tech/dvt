from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from ...domain import (
    SqlReferenceExtractionError,
    SqlTableRef,
    SqlTableReferenceExtractor,
    SqlTableReferences,
)
from ._sql_render import render_sql, sqlglot_dialect


class SqlglotTableReferenceExtractor(SqlTableReferenceExtractor):
    def extract(
        self,
        sql: str,
        dialect: str,
        project_variables: Mapping[str, Any],
    ) -> SqlTableReferences:
        rendered, used_project_variables = render_sql(sql, dialect, project_variables)

        try:
            statements = sqlglot.parse(rendered, read=sqlglot_dialect(dialect))
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
