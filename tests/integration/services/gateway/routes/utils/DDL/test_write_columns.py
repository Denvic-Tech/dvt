"""Real Gateway write-column operations against isolated PostgreSQL and ClickHouse sources."""

from uuid import uuid4

import pytest
import sqlalchemy as sa
from clickhouse_sqlalchemy import Table as ClickHouseTable, engines, types as ch_types

from services.gateway.routes.utils.DDL.table import (
    apply_table_column_actions_from_connection_string as apply_actions,
    resolve_write_columns_from_connection_string as resolve_columns,
)

from src.schemas.http.create_table import ApplyTableColumnActionsRequest, ResolveWriteColumnsRequest

pytest_plugins = ["tests.integration.fixtures.db_comments"]
pytestmark = [pytest.mark.docker_required, pytest.mark.asyncio]


@pytest.fixture
def ddl_table(comments_engine):
    engine = comments_engine
    name = "mcp_ddl_" + uuid4().hex[:10]
    if engine.dialect.name == "clickhouse":
        table = ClickHouseTable(
            name, sa.MetaData(),
            sa.Column("id", ch_types.Int32()),
            sa.Column("value", ch_types.Nullable(ch_types.String())),
            engines.MergeTree(order_by="id"),
        )
    else:
        table = sa.Table(
            name, sa.MetaData(), sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("value", sa.String(64), nullable=True),
        )
    table.create(engine)
    try:
        with engine.begin() as conn:
            conn.execute(table.insert(), [{"id": 1, "value": "one"}, {"id": 2, "value": "two"}])
        yield table
    finally:
        table.drop(engine)


def target(engine, table):
    return {
        "connection_id": "test-source",
        "database_name": engine.url.database,
        "table_name": table.name,
    }


def columns(engine, table):
    return {col["name"]: col for col in sa.inspect(engine).get_columns(table.name)}


def rows(engine, table):
    with engine.connect() as connection:
        return connection.execute(sa.select(table).order_by(table.c.id)).all()


@pytest.mark.parametrize("comments_engine", ["postgresql", "clickhouse"], indirect=True)
async def test_resolution_preview_and_column_lifecycle_preserve_existing_rows(
    comments_engine, ddl_table,
):
    engine, table = comments_engine, ddl_table
    url = engine.url.render_as_string(hide_password=False)
    before = rows(engine, table)
    resolution = await resolve_columns(ResolveWriteColumnsRequest(
        **target(engine, table), mode="existing_table",
        dataframe_metadata={"columns": [
            {"name": "id", "dtype": "INT", "nullable": False},
            {"name": "label", "dtype": "STRING", "nullable": True},
            {"name": "email", "dtype": "STRING", "nullable": True},
        ]},
        column_mapping=[{"source_name": "label", "target_name": "value"}],
    ), url)
    assert any(c.status == "missing_in_db" and c.source_name == "email"
               for c in resolution.columns)
    assert any(m.source_name == "label" and m.target_name == "value"
               for m in resolution.effective_column_mapping)
    assert "email" not in columns(engine, table)
    assert rows(engine, table) == before

    request = ApplyTableColumnActionsRequest(
        **target(engine, table),
        actions=[{"type": "add_column", "column_name": "email",
                  "column": {"name": "email", "dtype": "STRING", "nullable": True}}],
        dry_run=True,
    )
    preview = apply_actions(request, url)
    assert preview.sql and preview.table_metadata is None
    assert "email" not in columns(engine, table)
    assert rows(engine, table) == before
    request.dry_run = False
    applied = apply_actions(request, url)
    assert applied.sql == preview.sql
    assert next(c for c in applied.table_metadata.columns if c.name == "email").nullable is True
    assert rows(engine, table) == before

    # Nullability/comment edits preserve old values. No concurrent writers in this fixture.
    change = ApplyTableColumnActionsRequest(
        **target(engine, table), dry_run=False,
        actions=[
            {"type": "set_column_nullable", "column_name": "value", "nullable": False},
            {"type": "set_column_comment", "column_name": "value", "comment": "Client label"},
        ],
    )
    result = apply_actions(change, url)
    value = next(c for c in result.table_metadata.columns if c.name == "value")
    assert value.nullable is False and value.comment == "Client label"
    assert rows(engine, table) == before
    change = ApplyTableColumnActionsRequest(
        **target(engine, table), actions=[
            {"type": "set_column_nullable", "column_name": "value", "nullable": True},
            {"type": "set_column_comment", "column_name": "value", "comment": None},
        ],
    )
    result = apply_actions(change, url)
    value = next(c for c in result.table_metadata.columns if c.name == "value")
    assert value.nullable is True and value.comment is None

    # A NULL check must reject the entire batch before adding an unrelated column.
    fail = ApplyTableColumnActionsRequest(
        **target(engine, table), dry_run=True,
        actions=[
            {"type": "add_column", "column_name": "must_not_exist",
             "column": {"name": "must_not_exist", "dtype": "INT", "nullable": True}},
            {"type": "set_column_nullable", "column_name": "email", "nullable": False},
        ],
    )
    assert apply_actions(fail, url).sql  # Preview does not scan existing NULLs.
    fail.dry_run = False
    with pytest.raises(Exception, match="NULL"):
        apply_actions(fail, url)
    assert "must_not_exist" not in columns(engine, table)
    assert rows(engine, table) == before

    # Recreate explicitly discards values; drop removes the column.
    recreated = apply_actions(ApplyTableColumnActionsRequest(
        **target(engine, table), actions=[{
            "type": "recreate_column", "column_name": "value",
            "column": {"name": "value", "dtype": "STRING", "nullable": True},
        }],
    ), url)
    assert recreated.table_metadata is not None
    with engine.connect() as connection:
        assert connection.execute(sa.select(table).order_by(table.c.id)).all() == [
            (1, None), (2, None),
        ]
    dropped = apply_actions(ApplyTableColumnActionsRequest(
        **target(engine, table), actions=[{"type": "drop_column", "column_name": "email"}],
    ), url)
    assert "email" not in {c.name for c in dropped.table_metadata.columns}


@pytest.mark.parametrize("comments_engine", ["postgresql", "clickhouse"], indirect=True)
async def test_typed_create_resolution_does_not_create_table(comments_engine):
    engine = comments_engine
    name = "mcp_preview_missing"
    result = await resolve_columns(ResolveWriteColumnsRequest(
        connection_id="test", database_name=engine.url.database, table_name=name,
        mode="typed_create", dataframe_metadata={"columns": [
            {"name": "source", "dtype": "INT", "nullable": False},
        ]}, column_mapping=[{"source_name": "source", "target_name": "target"}],
    ), engine.url.render_as_string(hide_password=False))
    assert result.effective_column_mapping[0].target_name == "target"
    assert not sa.inspect(engine).has_table(name)
