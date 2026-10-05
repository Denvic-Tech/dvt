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


@pytest.mark.parametrize("dialect", ["mssql", "tsql"])
@pytest.mark.parametrize(
    ("template", "expected"),
    [
        (
            "SELECT TOP ({{ input_variables.batch_limit }}) * FROM events",
            "SELECT TOP (10) * FROM events",
        ),
        (
            "select top ( {{ batch_limit | int }} ) * from events",
            "select top ( 10 ) * from events",
        ),
        (
            "SELECT TOP (({{ batch_limit }})) * FROM events",
            "SELECT TOP ((10)) * FROM events",
        ),
        (
            "SELECT TOP (/* batch size */ {{ batch_limit }}) * FROM events",
            "SELECT TOP (/* batch size */ 10) * FROM events",
        ),
        (
            "SELECT TOP ({{ batch_limit }}) PERCENT WITH TIES * FROM events ORDER BY id",
            "SELECT TOP (10) PERCENT WITH TIES * FROM events ORDER BY id",
        ),
    ],
)
def test_renders_mssql_top_value(template: str, expected: str, dialect: str) -> None:
    assert _render(template, {"batch_limit": 10}, dialect) == expected


def test_renders_nested_top_and_other_interpolations() -> None:
    assert _render(
        "SELECT TOP ({{ outer_limit }}) * FROM "
        "(SELECT TOP ({{ inner_limit }}) * FROM {{ table }} WHERE status = {{ status }}) AS src "
        "ORDER BY {{ column }}",
        {
            "outer_limit": 10,
            "inner_limit": 100,
            "column": "id",
            "table": "dbo.events",
            "status": "active",
        },
        "mssql",
    ) == (
        "SELECT TOP (10) * FROM "
        "(SELECT TOP (100) * FROM [dbo].[events] WHERE status = 'active') AS src "
        "ORDER BY [id]"
    )


def test_top_string_value_cannot_inject_sql() -> None:
    assert _render(
        "SELECT TOP ({{ batch_limit }}) * FROM events",
        {"batch_limit": "10'); DROP TABLE events; --"},
        "mssql",
    ) == "SELECT TOP ('10''); DROP TABLE events; --') * FROM events"


def test_keeps_top_cast_workaround() -> None:
    assert _render(
        "SELECT TOP (CAST('{{ batch_limit }}' AS bigint)) * FROM events",
        {"batch_limit": 10},
        "mssql",
    ) == "SELECT TOP (CAST('10' AS bigint)) * FROM events"


@pytest.mark.parametrize(
    "template",
    [
        "SELECT TOP (1) * FROM events /* TOP ( */ {{ fragment }}",
        "SELECT TOP (dvt_template_0) * FROM events {{ fragment }}",
        "SELECT TOP ([{{ fragment }}]) * FROM events",
    ],
)
def test_rejects_false_top_literal_positions(template: str) -> None:
    with pytest.raises(SQLTemplateContextError, match="Raw SQL fragments"):
        _render(template, {"fragment": "WHERE id = 1"}, "mssql")


def test_rejects_raw_sql_fragment_position() -> None:
    with pytest.raises(SQLTemplateContextError, match="Raw SQL fragments"):
        _render("SELECT * FROM events {{ fragment }}", {"fragment": "WHERE id = 1"})


def test_renders_top_from_snapshot_batch_query() -> None:
    template = """
SELECT TOP ({{input_variables.batch_limit}})
    SourceTable.[ДатаИзменения]
    ,SourceTable.[УУ_РабочееМесто] AS "УУ_РабочееМесто"
    ,SourceTable.[Инициалы]
    ,SourceTable.[Пол]
    ,SourceTable.[УУ_УдаленнаяРабота] AS "УУ_УдаленнаяРабота"
    ,SourceTable.[Код]
    ,CAST(SourceTable.[ПараметрСсылка] AS VARCHAR(36)) AS "ПараметрСсылка"
    ,SourceTable.[УУ_СтатусВКомпании] AS "УУ_СтатусВКомпании"
    ,SourceTable.[ДатаРегистрации]
FROM [TS_EXTRA_DATA_01].[dbo].[TestParquetS3] AS SourceTable
LEFT JOIN [TS_EXTRA_DATA_01].[dbo].[SnapshotTestParquetS3] AS Snapshot
    ON SourceTable.ПараметрСсылка = Snapshot.ПараметрСсылка
    AND ISNULL(SourceTable.Пол, '') = ISNULL(Snapshot.Пол, '')
    AND ISNULL(SourceTable.ДатаРегистрации, '') = ISNULL(Snapshot.ДатаРегистрации, '')
    AND ISNULL(SourceTable.Инициалы, '') = ISNULL(Snapshot.Инициалы, '')
    AND ISNULL(SourceTable.УУ_РабочееМесто, '') = ISNULL(Snapshot.УУ_РабочееМесто, '')
    AND ISNULL(SourceTable.УУ_СтатусВКомпании, '') = ISNULL(Snapshot.УУ_СтатусВКомпании, '')
    AND ISNULL(SourceTable.УУ_УдаленнаяРабота, '') = ISNULL(Snapshot.УУ_УдаленнаяРабота, '')
    AND ISNULL(SourceTable.Код, '') = ISNULL(Snapshot.Код, '')
WHERE SourceTable.ДатаИзменения >= (
    SELECT ISNULL(MAX(Snapshot.ДатаИзменения), '1900-01-01') AS "МаксДатаИзменения"
    FROM [TS_EXTRA_DATA_01].[dbo].[SnapshotTestParquetS3] AS Snapshot
)
    AND Snapshot.ПараметрСсылка IS NULL
ORDER BY [ДатаИзменения]
"""
    assert _render(template, {"batch_limit": 1000}, "mssql") == template.replace(
        "{{input_variables.batch_limit}}", "1000"
    )
