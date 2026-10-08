from datetime import UTC, datetime, timedelta

import pytest

from src.modules.data_catalog.domain import (
    CatalogViewer,
    Dataset,
    FieldStatus,
    ObservedField,
    PhysicalLocator,
    SchemaActor,
    ViewerScope,
)
from src.modules.data_catalog.flow import SyncDatasetSchema

from ..fakes import (
    FakeSchemaSource,
    InMemoryConnectionRepository,
    InMemoryDatasetRepository,
    InMemoryFieldRepository,
)

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
VIEWER = CatalogViewer("u", "org", ViewerScope.OWN)
ACTOR = SchemaActor("u", "org", "user")


def _dataset(synced_at=None) -> Dataset:
    return Dataset(
        id="d1",
        organization_id="org",
        locator=PhysicalLocator("postgresql", "db", 5432, "main", "public", "t"),
        physical_key="postgresql://db:5432/main/public/t",
        created_at=NOW,
        updated_at=NOW,
        schema_synced_at=synced_at,
    )


def _use_case(source, *, usable=("conn-1",), ttl=300):
    datasets = InMemoryDatasetRepository()
    fields = InMemoryFieldRepository()
    return (
        SyncDatasetSchema(
            datasets=datasets,
            fields=fields,
            connections=InMemoryConnectionRepository(usable=usable),
            schema_source=source,
            ttl_seconds=ttl,
            clock=lambda: NOW,
            id_factory=iter(f"id-{i}" for i in range(100)).__next__,
        ),
        datasets,
        fields,
    )


@pytest.mark.asyncio
async def test_sync_fetches_fields_and_stamps_dataset():
    source = FakeSchemaSource([ObservedField("id", "integer"), ObservedField("name", "text")])
    use_case, datasets, fields = _use_case(source)
    dataset = _dataset()

    outcome = await use_case.execute(dataset=dataset, viewer=VIEWER, actor=ACTOR)

    assert outcome.status == "synced"
    assert outcome.new == 2
    assert dataset.schema_synced_at == NOW
    assert {f.name: f.status for f in await fields.list_for_dataset("d1")} == {
        "id": FieldStatus.NEW,
        "name": FieldStatus.NEW,
    }
    assert datasets.items["d1"] is dataset


@pytest.mark.asyncio
async def test_sync_is_skipped_inside_ttl_unless_forced():
    source = FakeSchemaSource([ObservedField("id", "integer")])
    use_case, _, _ = _use_case(source)
    dataset = _dataset(synced_at=NOW - timedelta(seconds=60))

    assert (await use_case.execute(dataset=dataset, viewer=VIEWER, actor=ACTOR)).status == "skipped"
    assert source.calls == []
    assert (await use_case.execute(dataset=dataset, viewer=VIEWER, actor=ACTOR, force=True)).status == "synced"


@pytest.mark.asyncio
async def test_naive_timestamp_from_sqlite_is_treated_as_utc():
    use_case, _, _ = _use_case(FakeSchemaSource([ObservedField("id", "integer")]))
    dataset = _dataset(synced_at=(NOW - timedelta(seconds=60)).replace(tzinfo=None))
    assert (await use_case.execute(dataset=dataset, viewer=VIEWER, actor=ACTOR)).status == "skipped"


@pytest.mark.asyncio
async def test_source_failure_only_records_failed_check():
    use_case, _, fields = _use_case(FakeSchemaSource(fail=True))
    dataset = _dataset()

    outcome = await use_case.execute(dataset=dataset, viewer=VIEWER, actor=ACTOR)

    assert outcome.status == "failed"
    assert dataset.last_check_failed_at == NOW
    assert dataset.schema_synced_at is None
    assert await fields.list_for_dataset("d1") == []


@pytest.mark.asyncio
async def test_no_usable_connection_short_circuits():
    use_case, _, _ = _use_case(FakeSchemaSource([ObservedField("id", "integer")]), usable=())
    assert (await use_case.execute(dataset=_dataset(), viewer=VIEWER, actor=ACTOR)).status == "no_connection"


@pytest.mark.asyncio
async def test_not_found_source_error_is_classified_and_cleared_after_success():
    from src.modules.data_catalog.domain import CheckErrorKind, SchemaSourceNotFoundError

    class NotFoundSource(FakeSchemaSource):
        async def fetch_fields(self, **kwargs):
            raise SchemaSourceNotFoundError('database "DVT_Test" does not exist')

    use_case, _, _ = _use_case(NotFoundSource())
    dataset = _dataset()

    outcome = await use_case.execute(dataset=dataset, viewer=VIEWER, actor=ACTOR)

    assert outcome.status == "failed"
    assert outcome.error_kind is CheckErrorKind.NOT_FOUND
    assert dataset.last_check_error_kind is CheckErrorKind.NOT_FOUND
    assert 'database "DVT_Test" does not exist' in dataset.last_check_error

    healthy, _, _ = _use_case(FakeSchemaSource([ObservedField("id", "INT")]))
    assert (await healthy.execute(dataset=dataset, viewer=VIEWER, actor=ACTOR, force=True)).status == "synced"
    assert dataset.last_check_error is None and dataset.last_check_error_kind is None
