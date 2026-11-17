"""Ленивый repair проекций: сверка штампов и пересборка только устаревших проектов."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from ..domain import (
    LINEAGE_SCHEMA_VERSION,
    ProjectGraphGateway,
    ProjectionRepository,
    ProjectionStamp,
)
from ..domain.policies import is_projection_current, variables_fingerprint

if TYPE_CHECKING:
    from .use_cases.rebuild_project_catalog_projection import RebuildProjectCatalogProjection


class ProjectionFreshnessProvider:
    def __init__(
        self,
        *,
        projections: ProjectionRepository,
        graph_gateway: ProjectGraphGateway,
        rebuild: RebuildProjectCatalogProjection,
    ) -> None:
        self._projections = projections
        self._graph = graph_gateway
        self._rebuild = rebuild

    async def ensure_fresh(
        self,
        *,
        project_ids: Sequence[str],
        organization_id: str | None,
    ) -> list[str]:
        """Пересобирает проекции с устаревшим или отсутствующим штампом.

        organization_id ограничивает поиск проектов организацией viewer'а; None означает
        глобальный доступ. Для самой пересборки берётся организация проекта.
        Возвращает идентификаторы пересобранных проектов.
        """
        unique_ids = list(dict.fromkeys(project_ids))
        if not unique_ids:
            return []

        stored = await self._projections.get_many(unique_ids)
        rebuilt: list[str] = []
        for project_id in unique_ids:
            source = await self._graph.load_stamp_source(project_id, organization_id)
            if source is None:
                continue
            current = ProjectionStamp(
                graph_revision=source.graph_revision,
                variables_fingerprint=variables_fingerprint(source.variables),
                lineage_schema_version=LINEAGE_SCHEMA_VERSION,
            )
            if is_projection_current(stored.get(project_id), current):
                continue
            result = await self._rebuild.execute(
                project_id=project_id,
                organization_id=source.organization_id,
                force=False,
            )
            if result.status == "ok":
                rebuilt.append(project_id)
        return rebuilt
