import pytest

from src.modules.data_catalog.domain import SqlColumnKind, SqlSchemaHint
from src.modules.data_catalog.infra import SqlglotColumnLineageExtractor

HINT = SqlSchemaHint(tables={"orders": ("id", "amount", "cust"), "customers": ("id", "name"), "public.events": ("id", "kind")})


def _extract(sql: str, dialect: str = "postgresql", variables=None, hint=HINT):
    return SqlglotColumnLineageExtractor().extract(sql, dialect, variables or {}, hint)


def _columns(result):
    return {c.name: c for c in result.columns}


def test_aliases_aggregates_expressions_literals_and_cte_passthrough():
    result = _extract(
        """
        with o as (select cust, sum(amount) as total from orders group by cust)
        select c.id as customer_id, c.name, o.total, c.name || 'x' as tagged, 42 as answer,
               row_number() over (order by o.total) as rn
        from customers c join o on o.cust = c.id
        """
    )
    assert result.supported is True
    columns = _columns(result)
    assert columns["customer_id"].kind is SqlColumnKind.COLUMN
    assert [(s.reference, s.column) for s in columns["customer_id"].sources] == [("customers", "id")]
    assert columns["name"].kind is SqlColumnKind.COLUMN
    assert columns["total"].kind is SqlColumnKind.AGGREGATE
    assert [(s.reference, s.column) for s in columns["total"].sources] == [("orders", "amount")]
    assert columns["tagged"].kind is SqlColumnKind.EXPRESSION and "name" in (columns["tagged"].expression or "")
    assert columns["answer"].kind is SqlColumnKind.LITERAL
    assert columns["rn"].kind is SqlColumnKind.EXPRESSION, "window function is not an aggregate"


def test_star_is_expanded_from_schema_and_union_merges_branches():
    result = _extract("select * from customers union all select id, name from customers")
    columns = _columns(result)
    assert set(columns) == {"id", "name"}
    assert columns["id"].kind is SqlColumnKind.COLUMN
    assert [(s.reference, s.column) for s in columns["id"].sources] == [("customers", "id")]

    merged = _columns(_extract("select id from orders union all select id from customers"))
    assert merged["id"].kind is SqlColumnKind.UNION
    assert {s.reference for s in merged["id"].sources} == {"orders", "customers"}


def test_unknown_table_and_schema_qualified_reference():
    result = _extract("select e.kind, g.x from public.events e join ghost g on g.id = e.id")
    columns = _columns(result)
    assert [(s.reference, s.column) for s in columns["kind"].sources] == [("public.events", "kind")]
    assert columns["x"].sources == () or columns["x"].sources[0].reference == "ghost"


def test_templates_are_rendered_with_project_variables():
    result = _extract(
        "select id from {{ project_variables.tbl }}", variables={"tbl": "customers"}
    )
    assert result.supported is True
    assert [(s.reference, s.column) for s in result.columns[0].sources] == [("customers", "id")]


@pytest.mark.parametrize("sql", ["update orders set amount = 1", "select 1; select 2", "select from where"])
def test_non_select_multi_statement_and_broken_sql_are_unsupported(sql):
    result = _extract(sql)
    assert result.supported is False and result.error


def test_clickhouse_dialect_is_parsed():
    result = _extract("SELECT id, toString(amount) AS amount_text FROM orders", dialect="clickhouse")
    columns = _columns(result)
    assert columns["id"].kind is SqlColumnKind.COLUMN
    assert columns["amount_text"].kind is SqlColumnKind.EXPRESSION
