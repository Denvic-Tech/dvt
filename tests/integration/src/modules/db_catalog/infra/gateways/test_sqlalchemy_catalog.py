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
    finally:
        metadata.drop_all(engine, checkfirst=True)
        engine.dispose()
