from __future__ import annotations

from ...domain import (
    CatalogViewer,
    DatasetLinkRepository,
    DatasetNotFoundError,
    DatasetRepository,
    DatasetUsageEntry,
    LinkDirection,
)
from ..providers import ProjectionFreshnessProvider


class GetDatasetUsage:
    def __init__(
        self,
        *,
        datasets: DatasetRepository,
        links: DatasetLinkRepository,
        freshness: ProjectionFreshnessProvider | None = None,
    ) -> None:
        self._datasets = datasets
        self._links = links
        self._freshness = freshness

    async def execute(
        self,
        *,
        dataset_id: str,
        viewer: CatalogViewer,
        direction: LinkDirection | None = None,
    ) -> list[DatasetUsageEntry]:
        dataset = await self._datasets.get_visible(dataset_id, viewer)
        if dataset is None:
            raise DatasetNotFoundError(f"Dataset {dataset_id} is not visible")

        if self._freshness is not None:
            project_ids = await self._links.list_project_ids(dataset.id, viewer)
            await self._freshness.ensure_fresh(
                project_ids=project_ids,
                organization_id=dataset.organization_id,
            )

        return await self._links.list_usage(dataset.id, viewer, direction)
