"""Column-level lineage SQL-запроса через sqlglot: колонки результата и их источники."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.lineage import Node, lineage
from sqlglot.optimizer.qualify import qualify

from ...domain import (
    SqlColumnKind,
    SqlColumnLineage,
    SqlColumnLineageExtractor,
    SqlLineageResult,
    SqlReferenceExtractionError,
    SqlSchemaHint,
    SqlSourceColumn,
)
from ._sql_render import render_sql, sqlglot_dialect

_MAX_EXPRESSION_LENGTH = 200
_LITERAL_TYPES = (exp.Literal, exp.Null, exp.Boolean)


class SqlglotColumnLineageExtractor(SqlColumnLineageExtractor):
    def extract(
        self,
        sql: str,
        dialect: str,
        project_variables: Mapping[str, Any],
        schema: SqlSchemaHint,
    ) -> SqlLineageResult:
        try:
            rendered, _ = render_sql(sql, dialect, project_variables)
        except SqlReferenceExtractionError as exc:
            return SqlLineageResult(supported=False, error=str(exc))

        read = sqlglot_dialect(dialect)
        try:
            statements = [item for item in sqlglot.parse(rendered, read=read) if item is not None]
        except (SqlglotError, ValueError) as exc:
            return SqlLineageResult(supported=False, error=f"parse: {exc}")
        if len(statements) != 1 or not isinstance(statements[0], exp.Query):
            return SqlLineageResult(supported=False, error="only a single SELECT statement is supported")

        raw = statements[0]
        sqlglot_schema = _schema_mapping(schema)
        try:
            qualified = qualify(raw.copy(), schema=sqlglot_schema, dialect=read)
        except Exception:
            try:
                qualified = qualify(raw.copy(), schema=sqlglot_schema, dialect=read, validate_qualify_columns=False)
            except Exception as exc:
                return SqlLineageResult(supported=False, error=f"qualify: {exc}")

        raw_names = list(raw.named_selects)
        qualified_names = list(qualified.named_selects)
        # Без `*` имена берём из исходного запроса: qualify приводит регистр в ряде диалектов.
        names = qualified_names if "*" in raw_names or len(raw_names) != len(qualified_names) else raw_names

        columns: list[SqlColumnLineage] = []
        for position, name in enumerate(names):
            lookup = qualified_names[position] if position < len(qualified_names) else name
            columns.append(_column_lineage(name, lookup, qualified, sqlglot_schema, read))
        return SqlLineageResult(columns=tuple(columns))


def _column_lineage(
    name: str,
    lookup: str,
    qualified: exp.Expression,
    schema: dict[str, Any],
    dialect: str,
) -> SqlColumnLineage:
    try:
        node = lineage(lookup, qualified, schema=schema, dialect=dialect)
    except Exception:
        return SqlColumnLineage(name=name, kind=SqlColumnKind.UNKNOWN, unknown_sources=True)

    sources: list[SqlSourceColumn] = []
    unknown = False
    aggregated_chain = False
    for item in node.walk():
        if _has_aggregate(item.expression):
            aggregated_chain = True
        if item.downstream:
            continue
        source = item.source
        if isinstance(source, exp.Table):
            column_name = _column_name(item)
            if column_name is None:
                unknown = True
                continue
            found = SqlSourceColumn(reference=_table_reference(source), column=column_name)
            if found not in sources:
                sources.append(found)
            continue
        leaf = _unalias(item.expression)
        if isinstance(leaf, _LITERAL_TYPES):
            continue
        unknown = True

    root = _unalias(node.expression)
    expression_text = root.sql(dialect=dialect)[:_MAX_EXPRESSION_LENGTH]
    # Колонка агрегирована, если агрегирует её собственное выражение или она переносит агрегат
    # из подзапроса как есть; выражение поверх агрегата остаётся вычислением.
    aggregated = _has_aggregate(node.expression) or (aggregated_chain and isinstance(root, exp.Column))
    if aggregated:
        kind = SqlColumnKind.AGGREGATE
    elif not sources and not unknown:
        kind = SqlColumnKind.LITERAL
    elif not sources:
        kind = SqlColumnKind.UNKNOWN
    elif isinstance(root, exp.Column):
        kind = SqlColumnKind.UNION if len(sources) > 1 else SqlColumnKind.COLUMN
    else:
        kind = SqlColumnKind.EXPRESSION
    return SqlColumnLineage(
        name=name,
        kind=kind,
        sources=tuple(sources),
        unknown_sources=unknown,
        expression=expression_text if kind in (SqlColumnKind.EXPRESSION, SqlColumnKind.AGGREGATE) else None,
    )


def _has_aggregate(expression: exp.Expression | None) -> bool:
    if expression is None:
        return False
    return any(agg.find_ancestor(exp.Window) is None for agg in expression.find_all(exp.AggFunc))


def _unalias(expression: exp.Expression) -> exp.Expression:
    return expression.this if isinstance(expression, exp.Alias) else expression


def _column_name(node: Node) -> str | None:
    expression = _unalias(node.expression)
    if isinstance(expression, exp.Column):
        return expression.name or None
    try:
        return exp.to_column(node.name).name or None
    except Exception:
        return None


def _table_reference(table: exp.Table) -> str:
    return ".".join(part for part in (table.catalog, table.db, table.name) if part).lower()


def _schema_mapping(schema: SqlSchemaHint) -> dict[str, Any]:
    """Схема для sqlglot с одним уровнем вложенности: по имени таблицы.

    sqlglot требует одинаковую глубину ключей, а ссылки каталога бывают и `table`, и `schema.table`.
    Таблица с неоднозначным именем (одно имя в разных схемах) в подсказку не попадает: тогда `*`
    по ней не раскрывается, а явные колонки резолвятся без схемы.
    """
    by_name: dict[str, list[tuple[str, ...]]] = {}
    for reference, columns in schema.tables.items():
        by_name.setdefault(reference.split(".")[-1], []).append(columns)
    return {
        name: dict.fromkeys(variants[0], "TEXT")
        for name, variants in by_name.items()
        if len(variants) == 1
    }
