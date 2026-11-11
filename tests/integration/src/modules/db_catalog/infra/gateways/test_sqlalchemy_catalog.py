import asyncio

import pytest
import sqlalchemy as sa

from src.modules.db_catalog.domain import (
    AuthorizedCatalogConnection,
    CatalogOperation,
    CatalogRequest,
    CatalogTablePreviewRequest,
)
from src.modules.db_catalog.infra.gateways.sqlalchemy_catalog import SQLAlchemyCatalogSource


def _source() -> SQLAlchemyCatalogSource:
    return SQLAlchemyCatalogSource(
        connect_timeout_seconds=5,
        query_timeout_seconds=30,
        request_timeout_seconds=40,
        max_concurrency=16,
    )


@pytest.mark.docker_required
def test_postgresql_catalog_accepts_empty_search_and_cursor(postgres_container):
    url = sa.make_url(postgres_container.get_connection_url())
    connection = AuthorizedCatalogConnection(
        id="conn",
        revision="revision",
        dialect="postgresql",
        configured_database=url.database,
        connection_url=url.render_as_string(hide_password=False),
    )

    result = asyncio.run(
        _source().fetch(
            connection,
            CatalogRequest(
                operation=CatalogOperation.DATABASES,
                limit=200,
            ),
        )
    )

    assert any(item.name == url.database and item.is_current for item in result.items)


@pytest.mark.docker_required
def test_postgresql_table_preview_reads_live_rows(postgres_container):
    url = sa.make_url(postgres_container.get_connection_url())
    engine = sa.create_engine(url)
    metadata = sa.MetaData()
    table = sa.Table(
        "catalog_preview_rows",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("value", sa.String(), nullable=False),
    )
    metadata.drop_all(engine, checkfirst=True)
    metadata.create_all(engine)
    try:
        with engine.begin() as db_connection:
            db_connection.execute(
                table.insert(),
                [{"id": 1, "value": "one"}, {"id": 2, "value": "two"}],
            )
        connection = AuthorizedCatalogConnection(
            id="conn",
            revision="revision",
            dialect="postgresql",
            configured_database=url.database,
            connection_url=url.render_as_string(hide_password=False),
        )

        result = asyncio.run(
            _source().fetch_preview(
                connection,
                CatalogTablePreviewRequest(
                    table_name=table.name,
                    schema_name="public",
                ),
            )
        )

        assert [column.name for column in result.columns] == ["id", "value"]
        assert set(result.rows) == {(1, "one"), (2, "two")}
        assert result.truncated is False
        assert (result.row_count, result.row_count_exact) == (2, True)

        with engine.begin() as db_connection:
            db_connection.execute(
                table.insert(),
                [{"id": index, "value": str(index)} for index in range(3, 121)],
            )
        request = CatalogTablePreviewRequest(table_name=table.name, schema_name="public")
        never_analyzed = asyncio.run(_source().fetch_preview(connection, request))
        with engine.begin() as db_connection:
            db_connection.exec_driver_sql(f"ANALYZE {table.name}")
        analyzed = asyncio.run(_source().fetch_preview(connection, request))

        assert never_analyzed.truncated is True
        assert never_analyzed.row_count is None or never_analyzed.row_count_exact is False
        assert (analyzed.row_count, analyzed.row_count_exact) == (120, False)
    finally:
        metadata.drop_all(engine, checkfirst=True)
        engine.dispose()


@pytest.mark.docker_required
@pytest.mark.parametrize(
    ("engine_fixture", "dialect", "ddl_suffix", "analyze", "exact"),
    [
        ("clickhouse_http_test_engine", "clickhouse", "ENGINE = MergeTree ORDER BY id", None, True),
        # MySQL 8 caches information_schema statistics until ANALYZE or the expiry interval.
        ("mysql_test_engine", "mysql", "", "ANALYZE TABLE catalog_row_count", False),
        ("mssql_test_engine", "mssql", "", None, False),
    ],
)
def test_large_table_row_count_is_read_from_system_catalog(
    request, engine_fixture, dialect, ddl_suffix, analyze, exact
):
    engine = request.getfixturevalue(engine_fixture)
    integer = "Int32" if dialect == "clickhouse" else "INT"
    values = ", ".join(f"({index})" for index in range(120))
    with engine.begin() as db_connection:
        db_connection.exec_driver_sql("DROP TABLE IF EXISTS catalog_row_count")
        db_connection.exec_driver_sql(
            f"CREATE TABLE catalog_row_count (id {integer} NOT NULL) {ddl_suffix}"
        )
        db_connection.exec_driver_sql(f"INSERT INTO catalog_row_count (id) VALUES {values}")
        if analyze:
            db_connection.exec_driver_sql(analyze)
    try:
        connection = AuthorizedCatalogConnection(
            id="conn",
            revision="revision",
            dialect=dialect,
            configured_database=engine.url.database,
            connection_url=engine.url.render_as_string(hide_password=False),
        )

        result = asyncio.run(
            _source().fetch_preview(
                connection,
                CatalogTablePreviewRequest(table_name="catalog_row_count"),
            )
        )

        assert len(result.rows) == 50
        assert (result.row_count, result.row_count_exact) == (120, exact)
    finally:
        with engine.begin() as db_connection:
            db_connection.exec_driver_sql("DROP TABLE IF EXISTS catalog_row_count")
