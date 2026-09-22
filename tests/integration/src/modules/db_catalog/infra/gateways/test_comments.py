from uuid import uuid4

import pytest
import sqlalchemy as sa
from tests.integration.fixtures.db_comments import (
    COLUMN_COMMENT,
    COMMENT_DIALECTS,
    TABLE_COMMENT,
)

from core.metadata import load_db_table_metadata

from src.modules.db_catalog.domain import (
    AuthorizedCatalogConnection,
    CatalogOperation,
    CatalogRequest,
    CatalogTableKind,
)
from src.modules.db_catalog.infra.gateways.sqlalchemy_catalog import SQLAlchemyCatalogSource

pytest_plugins = ["tests.integration.fixtures.db_comments"]
pytestmark = pytest.mark.docker_required


def _source():
    return SQLAlchemyCatalogSource(
        connect_timeout_seconds=10,
        query_timeout_seconds=30,
        request_timeout_seconds=40,
        max_concurrency=1,
    )


def _connection(engine):
    return AuthorizedCatalogConnection(
        id="comments",
        revision="r",
        dialect=engine.dialect.name,
        configured_database=engine.url.database,
        connection_url=engine.url.render_as_string(hide_password=False),
    )


@pytest.mark.parametrize("comments_engine", COMMENT_DIALECTS, indirect=True)
def test_native_comments_in_reflection_catalog_details_and_pages(comments_engine, commented_table):
    engine = comments_engine
    table = load_db_table_metadata(engine, table_name=commented_table.name)
    assert table.comment == TABLE_COMMENT
    assert [column.comment for column in table.columns] == [COLUMN_COMMENT, None]
    catalog = _source()
    connection = _connection(engine)
    details = catalog._fetch_table(
        engine,
        connection,
        CatalogRequest(
            operation=CatalogOperation.TABLE,
            table_name=commented_table.name,
        ),
    )
    assert details.table.comment == TABLE_COMMENT
    assert [column.comment for column in details.table.columns] == [COLUMN_COMMENT, None]
    page = catalog._fetch_page(
        engine,
        connection,
        CatalogRequest(
            operation=CatalogOperation.TABLES,
            search=commented_table.name,
        ),
    )
    assert [(item.name, item.comment) for item in page.items] == [
        (commented_table.name, TABLE_COMMENT)
    ]


@pytest.mark.parametrize("comments_engine", ["postgresql", "mssql", "oracle"], indirect=True)
def test_native_view_comments(comments_engine, commented_table):
    engine = comments_engine
    quote = engine.dialect.identifier_preparer.quote
    view_name = f"DvtView_{uuid4().hex[:10]}"
    view = sa.Table(
        view_name,
        sa.MetaData(),
        sa.Column("id", sa.Integer(), comment=COLUMN_COMMENT),
        sa.Column("value", sa.String()),
        comment=TABLE_COMMENT,
    )
    with engine.begin() as conn:
        conn.exec_driver_sql(
            f"CREATE VIEW {quote(view_name)} AS SELECT * FROM {quote(commented_table.name)}"
        )
    try:
        with engine.begin() as conn:
            if engine.dialect.name == "mssql":
                for column, comment in [(None, TABLE_COMMENT), ("id", COLUMN_COMMENT)]:
                    conn.execute(
                        sa.text("""
                        EXEC sp_addextendedproperty @name=N'MS_Description', @value=:comment,
                             @level0type=N'SCHEMA', @level0name=N'dbo',
                             @level1type=N'VIEW', @level1name=:name,
                             @level2type=:column_type, @level2name=:column
                    """),
                        {
                            "comment": comment,
                            "name": view_name,
                            "column": column,
                            "column_type": "COLUMN" if column else None,
                        },
                    )
            else:
                if engine.dialect.name == "postgresql":
                    literal = str(
                        sa.literal(TABLE_COMMENT).compile(
                            dialect=engine.dialect,
                            compile_kwargs={"literal_binds": True},
                        )
                    )
                    conn.exec_driver_sql(f"COMMENT ON VIEW {quote(view_name)} IS {literal}")
                else:
                    conn.execute(sa.schema.SetTableComment(view))
                conn.execute(sa.schema.SetColumnComment(view.c.id))
        result = _source()._fetch_table(
            engine,
            _connection(engine),
            CatalogRequest(
                operation=CatalogOperation.TABLE,
                table_name=view_name,
            ),
        )
        assert result.table.kind == CatalogTableKind.VIEW
        assert result.table.comment == TABLE_COMMENT
        assert result.table.columns[0].comment == COLUMN_COMMENT
        page = _source()._fetch_page(
            engine,
            _connection(engine),
            CatalogRequest(
                operation=CatalogOperation.TABLES,
                search=view_name,
            ),
        )
        assert page.items[0].comment == TABLE_COMMENT
    finally:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"DROP VIEW {quote(view_name)}")


@pytest.mark.parametrize("comments_engine", ["postgresql", "mssql"], indirect=True)
def test_comments_respect_same_table_name_in_different_schemas(comments_engine):
    engine = comments_engine
    schemas = [f"comments_{uuid4().hex[:8]}" for _ in range(2)]
    metadata = sa.MetaData()
    for i, schema in enumerate(schemas):
        sa.Table(
            "same_name",
            metadata,
            sa.Column("id", sa.Integer(), comment=f"column {i}"),
            schema=schema,
            comment=f"table {i}",
        )
    with engine.begin() as conn:
        for schema in schemas:
            conn.execute(sa.schema.CreateSchema(schema))
    try:
        metadata.create_all(engine)
        for i, schema in enumerate(schemas):
            request = CatalogRequest(
                operation=CatalogOperation.TABLE, schema_name=schema, table_name="same_name"
            )
            result = _source()._fetch_table(engine, _connection(engine), request)
            assert result.table.comment == f"table {i}"
            assert result.table.columns[0].comment == f"column {i}"
            page = _source()._fetch_page(
                engine,
                _connection(engine),
                CatalogRequest(
                    operation=CatalogOperation.TABLES,
                    schema_name=schema,
                ),
            )
            assert [(item.name, item.comment) for item in page.items] == [
                ("same_name", f"table {i}")
            ]
    finally:
        metadata.drop_all(engine)
        with engine.begin() as conn:
            for schema in schemas:
                conn.execute(sa.schema.DropSchema(schema))
