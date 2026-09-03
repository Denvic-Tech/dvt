from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp, parse_one
from sqlglot import parse


_READ_V3_MSSQL_QUERY_SHAPE_ERROR = (
    "read_v3 query mode on MSSQL supports a single SELECT query or top-level WITH ... SELECT. "
    "SQL batches/scripts (for example DECLARE, temp tables, EXEC, or multiple statements) "
    "are not supported."
)


@dataclass(frozen=True)
class EmbeddedQuerySpec:
    embedded_query_sql: str
    cte_prefix_sql: str
    relation_sql: str = "FROM user_query"


def build_read_v3_query_embedding(query: str, *, dialect_name: str) -> EmbeddedQuerySpec:
    normalized_query = (query or "").strip().rstrip(";")
    if not normalized_query:
        raise ValueError("query is empty")

    resolved_dialect = (dialect_name or "").lower()
    if resolved_dialect in {"mssql", "sqlserver"}:
        return _build_mssql_read_v3_query_embedding(normalized_query)

    return EmbeddedQuerySpec(
        embedded_query_sql=normalized_query,
        cte_prefix_sql=f"WITH user_query AS ({normalized_query})",
    )


def _parse_single_mssql_query(query: str) -> exp.Query:
    try:
        expressions = parse(query, read="tsql")
    except Exception as exc:  # pragma: no cover - defensive guard for non-standard SQL
        raise ValueError(_READ_V3_MSSQL_QUERY_SHAPE_ERROR) from exc

    if len(expressions) != 1 or not isinstance(expressions[0], exp.Query):
        raise ValueError(_READ_V3_MSSQL_QUERY_SHAPE_ERROR)
    return expressions[0]


def _build_user_query_cte(query_sql: str) -> exp.CTE:
    return exp.CTE(
        this=parse_one(query_sql, read="tsql"),
        alias=exp.TableAlias(this=exp.to_identifier("user_query")),
    )


def _build_mssql_read_v3_query_embedding(query: str) -> EmbeddedQuerySpec:
    expression = _parse_single_mssql_query(query)
    body_expression = expression.copy()
    body_expression.set("with_", None)
    embedded_query_sql = normalize_mssql_query_for_embedding(body_expression.sql(dialect="tsql"))

    original_with = expression.args.get("with_")
    if original_with is None:
        return EmbeddedQuerySpec(
            embedded_query_sql=embedded_query_sql,
            cte_prefix_sql=f"WITH user_query AS ({embedded_query_sql})",
        )

    cte_prefix_sql = exp.With(
        expressions=[
            *(cte.copy() for cte in original_with.expressions),
            _build_user_query_cte(embedded_query_sql),
        ],
        recursive=original_with.args.get("recursive"),
    ).sql(dialect="tsql")
    return EmbeddedQuerySpec(
        embedded_query_sql=embedded_query_sql,
        cte_prefix_sql=cte_prefix_sql,
    )


def normalize_mssql_query_for_embedding(query: str) -> str:
    normalized_query = (query or "").strip().rstrip(";")
    if not normalized_query:
        return normalized_query

    try:
        expression = parse_one(normalized_query, read="tsql")
    except Exception as exc:  # pragma: no cover - defensive guard for non-standard SQL
        raise ValueError(f"Failed to normalize MSSQL query for embedded execution:\n```\n{query}\n```") from exc
    if not isinstance(expression, exp.Query):
        return normalized_query

    if expression.args.get("order") is None:
        return normalized_query

    if any(expression.args.get(arg_name) is not None for arg_name in ("limit", "offset", "for_")):
        return normalized_query

    expression.set("offset", exp.Offset(expression=exp.Literal.number(0)))
    return expression.sql(dialect="tsql")
