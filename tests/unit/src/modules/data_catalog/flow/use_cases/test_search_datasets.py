from datetime import UTC, datetime

import pytest

from src.modules.data_catalog.domain import (
    LINEAGE_SCHEMA_VERSION,
    CatalogViewer,
    DatasetSearchQuery,
    ProjectCatalogProjection,
    ProjectGraphSnapshot,
    ProjectionStamp,
    ProjectionStatus,
    ProjectStampSource,
    RebuildResult,
    ViewerScope,
)
from src.modules.data_catalog.domain.policies import variables_fingerprint
from src.modules.data_catalog.flow import ProjectionFreshnessProvider, SearchDatasets

from ..fakes import FakeGraphGateway, InMemoryDatasetRepository, InMemoryProjectionRepository

NOW = datetime(2026, 10, 8, tzinfo=UTC)


class RecordingRebuild:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def execute(self, *, project_id, organization_id, force=False, raise_on_error=False):
        self.calls.append((project_id, organization_id))
        return RebuildResult(status="ok")


def _search(*, projection: ProjectCatalogProjection | None, project_revision: int = 7):
    projections = InMemoryProjectionRepository()
    if projection is not None:
        projections.items[projection.project_id] = projection
    graph = FakeGraphGateway(
        ProjectGraphSnapshot(stamp_source=ProjectStampSource("p1", "org-of-project", project_revision, None))
    )
    rebuild = RecordingRebuild()
    use_case = SearchDatasets(
        datasets=InMemoryDatasetRepository(),
        freshness=ProjectionFreshnessProvider(projections=projections, graph_gateway=graph, rebuild=rebuild),
    )
    return use_case, rebuild


@pytest.mark.asyncio
async def test_search_by_project_repairs_missing_projection_using_project_organization():
    use_case, rebuild = _search(projection=None)
    # Супер-админ: у viewer нет организации, организация берётся из проекта.
    viewer = CatalogViewer("admin", None, ViewerScope.ALL)

    await use_case.execute(viewer=viewer, query=DatasetSearchQuery(project_id="p1"))

    assert rebuild.calls == [("p1", "org-of-project")]


@pytest.mark.asyncio
async def test_search_by_project_skips_current_projection_and_general_search_never_repairs():
    current = ProjectCatalogProjection(
        "p1", "org-of-project", ProjectionStamp(7, variables_fingerprint(None), LINEAGE_SCHEMA_VERSION), NOW, ProjectionStatus.OK
    )
    use_case, rebuild = _search(projection=current)
    viewer = CatalogViewer("u", "org-of-project", ViewerScope.OWN)

    await use_case.execute(viewer=viewer, query=DatasetSearchQuery(project_id="p1"))
    assert rebuild.calls == []

    stale_case, stale_rebuild = _search(projection=None)
    await stale_case.execute(viewer=viewer, query=DatasetSearchQuery(text="orders"))
    assert stale_rebuild.calls == [], "общий поиск без project_id проекции не чинит"


@pytest.mark.asyncio
async def test_search_limit_is_clamped():
    use_case, _ = _search(projection=None)
    page = await use_case.execute(
        viewer=CatalogViewer("u", "org", ViewerScope.OWN), query=DatasetSearchQuery(limit=1000)
    )
    assert page.items == ()
