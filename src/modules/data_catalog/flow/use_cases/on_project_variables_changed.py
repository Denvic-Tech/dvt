from __future__ import annotations

from ...domain import ProjectionRepository, RebuildResult
from .rebuild_project_catalog_projection import RebuildProjectCatalogProjection


class OnProjectVariablesChanged:
    """Пересобирает проекцию только если она зависит от переменных проекта."""

    def __init__(
        self,
        *,
        projections: ProjectionRepository,
        rebuild: RebuildProjectCatalogProjection,
    ) -> None:
        self._projections = projections
        self._rebuild = rebuild

    async def execute(self, *, project_id: str, organization_id: str) -> RebuildResult:
        projection = await self._projections.get(project_id)
        if projection is None or not projection.depends_on_project_variables:
            return RebuildResult(status="skipped", projection=projection)
        return await self._rebuild.execute(
            project_id=project_id,
            organization_id=organization_id,
            force=False,
        )
