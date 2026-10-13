from datetime import UTC, datetime

import pytest

from src.modules.data_catalog.domain import (
    LINEAGE_SCHEMA_VERSION,
    CatalogViewer,
    Dataset,
    DatasetLink,
    DatasetNotFoundError,
    LinkDirection,
    ProjectCatalogProjection,
    ProjectGraphSnapshot,
    ProjectionStamp,
    ProjectionStatus,
    ProjectStampSource,
    ResolvedVia,
    ViewerScope,
    db_table_locator,
)
from src.modules.data_catalog.domain.policies import variables_fingerprint
from src.modules.data_catalog.flow import GetDatasetUsage, ProjectionFreshnessProvider

from ..fakes import (
    FakeGraphGateway,
    InMemoryDatasetRepository,
    InMemoryLinkRepository,
    InMemoryProjectionRepository,
)

NOW = datetime(2026, 10, 7, tzinfo=UTC)
VIEWER = CatalogViewer("u", "org", ViewerScope.OWN)


class RecordingRebuild:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def execute(self, *, project_id, organization_id, force=False, raise_on_error=False):
        self.calls.append(project_id)
        from src.modules.data_catalog.domain import RebuildResult

        return RebuildResult(status="ok")


def _dataset() -> Dataset:
    return Dataset(
        id="d1",
        organization_id="org",
        locator=db_table_locator("postgresql", "db", 5432, "main", "public", "t"),
        physical_key="k",
        created_at=NOW,
        updated_at=NOW,
    )


def _link(project_id: str, direction=LinkDirection.READ) -> DatasetLink:
    return DatasetLink(
        id=f"l-{project_id}",
        dataset_id="d1",
        project_id=project_id,
        organization_id="org",
        node_id="n",
        node_name="ReadTableFromDBV3",
        direction=direction,
        resolved_via=ResolvedVia.CONST,
        graph_revision=1,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.mark.asyncio
async def test_usage_repairs_stale_projections_before_listing():
    datasets = InMemoryDatasetRepository()
    datasets.items["d1"] = _dataset()
    links = InMemoryLinkRepository()
    links.by_project["fresh"] = [_link("fresh")]
    links.by_project["stale"] = [_link("stale", LinkDirection.WRITE)]
    projections = InMemoryProjectionRepository()
    projections.items["fresh"] = ProjectCatalogProjection(
        "fresh", "org", ProjectionStamp(7, variables_fingerprint(None), LINEAGE_SCHEMA_VERSION), NOW, ProjectionStatus.OK
    )
    projections.items["stale"] = ProjectCatalogProjection(
        "stale", "org", ProjectionStamp(1, variables_fingerprint(None), LINEAGE_SCHEMA_VERSION), NOW, ProjectionStatus.OK
    )
    graph = FakeGraphGateway(
        ProjectGraphSnapshot(stamp_source=ProjectStampSource("any", "org", 7, None))
    )
    rebuild = RecordingRebuild()
    use_case = GetDatasetUsage(
        datasets=datasets,
        links=links,
        freshness=ProjectionFreshnessProvider(projections=projections, graph_gateway=graph, rebuild=rebuild),
    )

    entries = await use_case.execute(dataset_id="d1", viewer=VIEWER, direction=LinkDirection.WRITE)

    assert rebuild.calls == ["stale"], "пересобирается только проект с устаревшим штампом"
    assert [entry.project_id for entry in entries] == ["stale"]


@pytest.mark.asyncio
async def test_invisible_dataset_raises_not_found():
    use_case = GetDatasetUsage(datasets=InMemoryDatasetRepository(), links=InMemoryLinkRepository())
    with pytest.raises(DatasetNotFoundError):
        await use_case.execute(dataset_id="missing", viewer=VIEWER)
