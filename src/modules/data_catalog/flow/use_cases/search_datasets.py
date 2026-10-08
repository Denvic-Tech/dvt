from __future__ import annotations

from dataclasses import replace

from ...domain import CatalogViewer, DatasetRepository, DatasetSearchPage, DatasetSearchQuery
from ..providers import ProjectionFreshnessProvider

MAX_PAGE_SIZE = 200


class SearchDatasets:
    def __init__(
        self,
        *,
        datasets: DatasetRepository,
        freshness: ProjectionFreshnessProvider | None = None,
    ) -> None:
        self._datasets = datasets
        self._freshness = freshness

    async def execute(self, *, viewer: CatalogViewer, query: DatasetSearchQuery) -> DatasetSearchPage:
        limit = min(max(query.limit, 1), MAX_PAGE_SIZE)
        normalized = replace(
            query,
            text=(query.text or "").strip() or None,
            limit=limit,
        )
        # Поиск по проекту чинит его проекцию лениво: проект, который никогда не сохранялся
        # после появления каталога, иначе выглядел бы пустым. Общий поиск так не чинится,
        # это задача backfill.
        if normalized.project_id and self._freshness is not None:
            await self._freshness.ensure_fresh(
                project_ids=[normalized.project_id],
                organization_id=viewer.organization_id,
            )
        return await self._datasets.search(viewer, normalized)
