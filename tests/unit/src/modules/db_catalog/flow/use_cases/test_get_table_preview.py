import pytest

from src.modules.db_catalog.domain import (
    AuthorizedCatalogConnection,
    CatalogActor,
    CatalogTablePreview,
    CatalogTablePreviewColumn,
)
from src.modules.db_catalog.flow import GetTablePreviewUseCase


class FakeConnectionAccess:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    async def get_authorized(self, connection_id, actor):
        self._events.append("authorize")
        return AuthorizedCatalogConnection(
            id=connection_id,
            revision="revision",
            dialect="postgresql",
            configured_database="analytics",
            connection_url="postgresql://user:secret@db/analytics",
        )


class FakeTablePreviewSource:
    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.requests = []

    async def fetch_preview(self, connection, request):
        self._events.append("source")
        self.requests.append(request)
        return CatalogTablePreview(
            columns=(CatalogTablePreviewColumn(name="id", dtype="INT"),),
            rows=((1,),),
        )


@pytest.mark.asyncio
async def test_table_preview_authorizes_each_live_read_without_catalog_cache():
    events: list[str] = []
    source = FakeTablePreviewSource(events)
    use_case = GetTablePreviewUseCase(
        connection_access=FakeConnectionAccess(events),
        source=source,
    )
    actor = CatalogActor("user", "org", "user")

    first = await use_case.execute(
        connection_id="connection",
        actor=actor,
        database_name="analytics",
        schema_name="public",
        table_name="orders",
    )
    second = await use_case.execute(
        connection_id="connection",
        actor=actor,
        database_name="analytics",
        schema_name="public",
        table_name="orders",
    )

    assert events == ["authorize", "source", "authorize", "source"]
    assert len(source.requests) == 2
    assert source.requests[0].table_name == "orders"
    assert first.preview.rows == ((1,),)
    assert second.dialect == "postgresql"
