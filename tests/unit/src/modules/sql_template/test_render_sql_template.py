from __future__ import annotations

import pytest

from src.modules.sql_template import (
    CallbackSQLExpressionEvaluator,
    SQLTemplateContextError,
    SQLTemplateRenderRequest,
    SQLTemplateSerializationError,
    build_render_sql_template_use_case,
)
from src.node_dsl.input_expressions import evaluate_input_expression


def _renderer():
    evaluator = CallbackSQLExpressionEvaluator(
        lambda expression, variables, project_variables: evaluate_input_expression(
            expression=expression,
            variables=variables,
            project_variables=project_variables,
            expression_kind="single",
            expression_policy="default",
        )
    )
    return build_render_sql_template_use_case(), evaluator


def _render(template: str, variables: dict, dialect: str = "postgres") -> str:
    renderer, evaluator = _renderer()
    return renderer.execute(
        SQLTemplateRenderRequest(
            template=template,
            variables=variables,
            project_variables=variables,
            dialect_name=dialect,
            expression_evaluator=evaluator,
        )
    ).sql


def test_escapes_apostrophe_inside_quoted_literal_from_incident() -> None:
    sql = _render(
        "INSERT INTO errors (time, error) VALUES ('{{ input_variables.time }}', "
        "'{{ input_variables.error }}')",
        {
            "time": "2026-08-13 18:01:59",
            "error": "Unknown table expression identifier 'my_table_1'",
        },
        "clickhouse",
    )

    assert "'Unknown table expression identifier ''my_table_1'''" in sql


@pytest.mark.parametrize(
    ("template", "variables", "expected"),
    [
        ("SELECT * FROM events WHERE name = {{ name }}", {"name": "O'Reilly"}, "name = 'O''Reilly'"),
        ("SELECT * FROM events WHERE deleted_at = {{ value }}", {"value": None}, "deleted_at = NULL"),
        ("SELECT * FROM events WHERE id IN ({{ ids }})", {"ids": [1, 2]}, "IN (1, 2)"),
        ("INSERT INTO events(id, code) VALUES (1, {{ code }})", {"code": "A"}, "VALUES (1, 'A')"),
        ("SELECT * FROM events LIMIT {{ limit | int }}", {"limit": "10"}, "LIMIT 10"),
    ],
)
def test_renders_bare_value_positions(template: str, variables: dict, expected: str) -> None:
    assert expected in _render(template, variables)


def test_rejects_empty_collection() -> None:
    with pytest.raises(SQLTemplateSerializationError, match="Empty collections"):
        _render("SELECT * FROM events WHERE id IN ({{ ids }})", {"ids": []})


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        ("clickhouse", "SELECT `name` FROM `warehouse`.`events`"),
        ("postgres", 'SELECT "name" FROM "warehouse"."events"'),
        ("mssql", "SELECT [name] FROM [warehouse].[events]"),
    ],
)
def test_quotes_dynamic_identifiers_by_dialect(dialect: str, expected: str) -> None:
    assert _render(
        "SELECT {{ column }} FROM {{ table }}",
        {"column": "name", "table": "warehouse.events"},
        dialect,
    ) == expected


def test_supports_insert_column_and_update_set_value() -> None:
    assert _render(
        "INSERT INTO events ({{ column }}) VALUES ({{ value }})",
        {"column": "event_name", "value": "created"},
    ) == 'INSERT INTO events ("event_name") VALUES (\'created\')'
    assert _render(
        "UPDATE events SET name = {{ value }}",
        {"value": "updated"},
    ) == "UPDATE events SET name = 'updated'"
    assert _render(
        "UPDATE events SET {{ column }} = {{ value }}",
        {"column": "name", "value": "updated"},
    ) == 'UPDATE events SET "name" = \'updated\''


def test_rejects_raw_sql_fragment_position() -> None:
    with pytest.raises(SQLTemplateContextError, match="Raw SQL fragments"):
        _render("SELECT * FROM events {{ fragment }}", {"fragment": "WHERE id = 1"})
