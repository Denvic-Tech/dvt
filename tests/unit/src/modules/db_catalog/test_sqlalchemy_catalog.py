import asyncio

import pytest
import sqlalchemy as sa

from src.modules.db_catalog.domain import (
    AuthorizedCatalogConnection,
    CatalogOperation,
    CatalogRequest,
    CatalogTableKind,
)
from src.modules.db_catalog.infra.gateways.sqlalchemy_catalog import SQLAlchemyCatalogSource


def _source() -> SQLAlchemyCatalogSource:
    return SQLAlchemyCatalogSource(
        connect_timeout_seconds=5,
        query_timeout_seconds=30,
        request_timeout_seconds=40,
        max_concurrency=16,
    )


def test_sqlite_catalog_uses_paged_summaries_and_targeted_table_details(tmp_path):
    path = tmp_path / "catalog.sqlite"
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        for name in ("alpha", "beta", "gamma"):
            connection.exec_driver_sql(
                f'CREATE TABLE "{name}" (id INTEGER PRIMARY KEY, value TEXT)'
            )
        connection.exec_driver_sql("CREATE VIEW alpha_view AS SELECT * FROM alpha")
    engine.dispose()

    connection = AuthorizedCatalogConnection(
        id="conn",
        revision="revision",
        dialect="sqlite",
        configured_database=str(path),
        connection_url=sa.URL.create(
            "sqlite+pysqlite",
            database=str(path),
        ).render_as_string(hide_password=False),
    )

    first_page = asyncio.run(_source().fetch(
        connection,
        CatalogRequest(
            operation=CatalogOperation.TABLES,
            schema_name="main",
            limit=2,
        ),
    ))
    second_page = asyncio.run(_source().fetch(
        connection,
        CatalogRequest(
            operation=CatalogOperation.TABLES,
            schema_name="main",
            limit=2,
            cursor=first_page.next_cursor,
        ),
    ))
    detail = asyncio.run(_source().fetch(
        connection,
        CatalogRequest(
            operation=CatalogOperation.TABLE,
            schema_name="main",
            table_name="alpha",
        ),
    ))

    assert len(first_page.items) == 2
    assert first_page.next_cursor is not None
    assert {item.name for item in first_page.items}.isdisjoint(
        {item.name for item in second_page.items}
    )
    assert all(not hasattr(item, "columns") for item in first_page.items)
    assert detail.table.name == "alpha"
    assert [column.name for column in detail.table.columns] == ["id", "value"]
    assert detail.table.columns[0].primary_key is True


def test_sqlite_catalog_filters_views_at_source(tmp_path):
    path = tmp_path / "views.sqlite"
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE base_table (id INTEGER)")
        connection.exec_driver_sql("CREATE VIEW only_view AS SELECT * FROM base_table")
    engine.dispose()
    catalog_connection = AuthorizedCatalogConnection(
        id="conn",
        revision="revision",
        dialect="sqlite",
        configured_database=str(path),
        connection_url=sa.URL.create(
            "sqlite+pysqlite", database=str(path)
        ).render_as_string(hide_password=False),
    )

    result = asyncio.run(_source().fetch(
        catalog_connection,
        CatalogRequest(
            operation=CatalogOperation.TABLES,
            schema_name="main",
            kinds=(CatalogTableKind.VIEW,),
        ),
    ))

    assert [(item.name, item.kind) for item in result.items] == [
        ("only_view", CatalogTableKind.VIEW)
    ]


@pytest.mark.parametrize(
    ("dialect", "pagination_marker"),
    [
        ("postgresql", "LIMIT :row_limit"),
        ("mysql", "LIMIT :row_limit"),
        ("mariadb", "LIMIT :row_limit"),
        ("mssql", "SELECT TOP (26)"),
        ("sqlserver", "SELECT TOP (26)"),
        ("clickhouse", "LIMIT :row_limit"),
        ("oracle", "FETCH FIRST 26 ROWS ONLY"),
        ("sqlite", "LIMIT :row_limit"),
    ],
)
def test_supported_dialects_build_filtered_source_queries(dialect, pagination_marker):
    source = _source()
    connection = AuthorizedCatalogConnection(
        id="conn",
        revision="revision",
        dialect=dialect,
        configured_database="analytics",
        connection_url="sqlite+pysqlite:///:memory:",
    )
    request = CatalogRequest(
        operation=CatalogOperation.TABLES,
        database_name="analytics",
        schema_name="public" if dialect != "sqlite" else "main",
        search="orders",
        limit=25,
        kinds=(CatalogTableKind.TABLE, CatalogTableKind.VIEW),
    )

    statement, params = source._build_page_query(connection, request)

    assert pagination_marker in statement
    assert "ORDER BY" in statement
    assert params["search"] == "%orders%"
    assert params["row_limit"] == 26


def test_postgresql_catalog_types_nullable_filter_parameters():
    source = _source()
    connection = AuthorizedCatalogConnection(
        id="conn",
        revision="revision",
        dialect="postgresql",
        configured_database="analytics",
        connection_url="postgresql+psycopg://user:password@localhost/analytics",
    )
    request = CatalogRequest(
        operation=CatalogOperation.DATABASES,
        limit=200,
    )

    statement, params = source._build_page_query(connection, request)

    assert "CAST(:search AS TEXT) IS NULL" in statement
    assert "CAST(:cursor_norm AS TEXT) IS NULL" in statement
    assert "CAST(:cursor_exact AS TEXT)" in statement
    assert params["search"] is None
    assert params["cursor_norm"] is None
    assert params["cursor_exact"] is None
