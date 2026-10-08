from datetime import UTC, datetime

import pytest

from src.modules.data_catalog.domain import (
    CatalogViewer,
    Dataset,
    DatasetLink,
    LinkDirection,
    ObservedField,
    PhysicalLocator,
    ResolvedVia,
    SchemaActor,
    ViewerScope,
)
from src.modules.data_catalog.flow import RefreshDatasetSchema, SyncDatasetSchema

from ..fakes import (
    FakeSchemaSource,
    InMemoryConnectionRepository,
    InMemoryDatasetRepository,
    InMemoryFieldRepository,
    InMemoryLinkRepository,
)

NOW = datetime(2026, 10, 7, tzinfo=UTC)
VIEWER = CatalogViewer("u", "org", ViewerScope.OWN)
ACTOR = SchemaActor("u", "org", "user")


def _harness(source, *, usable=("conn-1",)):
    datasets = InMemoryDatasetRepository()
    dataset = Dataset(
        id="d1",
        organization_id="org",
        locator=PhysicalLocator("postgresql", "db", 5432, "main", "public", "t"),
        physical_key="k",
        created_at=NOW,
        updated_at=NOW,
        schema_synced_at=NOW,
    )
    datasets.items["d1"] = dataset
    links = InMemoryLinkRepository()
    links.by_project["p1"] = [
        DatasetLink("l", "d1", "p1", "org", "n", "ReadTableFromDBV3", LinkDirection.READ, ResolvedVia.CONST, 1, NOW, NOW)
    ]
    sync = SyncDatasetSchema(
        datasets=datasets,
        fields=InMemoryFieldRepository(),
        connections=InMemoryConnectionRepository(usable=usable),
        schema_source=source,
        ttl_seconds=3600,
        clock=lambda: NOW,
    )
    return RefreshDatasetSchema(datasets=datasets, links=links, sync_schema=sync), dataset, source


@pytest.mark.asyncio
async def test_refresh_bypasses_cache_ignores_ttl_and_reports_affected_projects():
    use_case, _, source = _harness(FakeSchemaSource([ObservedField("id", "INT"), ObservedField("x", "STRING")]))

    outcome = await use_case.execute(dataset_id="d1", viewer=VIEWER, actor=ACTOR)

    assert outcome.status == "synced"
    assert outcome.new == 2
    assert outcome.affected_project_ids == ("p1",)
    assert source.bypass_calls == [True], "refresh всегда идёт в источник мимо кэша"


@pytest.mark.asyncio
async def test_refresh_failure_is_reported_not_raised():
    use_case, dataset, _ = _harness(FakeSchemaSource(fail=True))

    outcome = await use_case.execute(dataset_id="d1", viewer=VIEWER, actor=ACTOR)

    assert outcome.status == "failed"
    assert outcome.error == "down"
    assert dataset.last_check_failed_at == NOW


@pytest.mark.asyncio
async def test_refresh_without_usable_connection():
    use_case, _, _ = _harness(FakeSchemaSource([ObservedField("id", "INT")]), usable=())
    assert (await use_case.execute(dataset_id="d1", viewer=VIEWER, actor=ACTOR)).status == "no_connection"
