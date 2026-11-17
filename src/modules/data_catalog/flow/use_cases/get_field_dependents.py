"""Кто зависит от поля сущности: колонки нод во всех видимых проектах-потребителях."""

from __future__ import annotations

from ...domain import (
    CatalogViewer,
    DatasetFieldNotFoundError,
    DatasetFieldRepository,
    DatasetLinkRepository,
    DatasetNotFoundError,
    DatasetRepository,
    FieldDependent,
    LineageRef,
    ProjectionRepository,
)
from ...domain.policies import collect_dependents, index_lineage
from ..providers import ProjectionFreshnessProvider

DEFAULT_MAX_DEPTH = 20
MAX_DEPTH_LIMIT = 100


class GetFieldDependents:
    def __init__(
        self,
        *,
        datasets: DatasetRepository,
        fields: DatasetFieldRepository,
        links: DatasetLinkRepository,
        projections: ProjectionRepository,
        freshness: ProjectionFreshnessProvider | None = None,
    ) -> None:
        self._datasets = datasets
        self._fields = fields
        self._links = links
        self._projections = projections
        self._freshness = freshness

    async def execute(
        self,
        *,
        dataset_id: str,
        field_id: str,
        viewer: CatalogViewer,
        max_depth: int = DEFAULT_MAX_DEPTH,
    ) -> list[FieldDependent]:
        dataset = await self._datasets.get_visible(dataset_id, viewer)
        if dataset is None:
            raise DatasetNotFoundError(f"Dataset {dataset_id} is not visible")
        fields = await self._fields.list_for_dataset(dataset.id)
        if not any(item.id == field_id for item in fields):
            raise DatasetFieldNotFoundError(f"Field {field_id} does not belong to dataset {dataset_id}")

        project_ids = await self._links.list_project_ids(dataset.id, viewer)
        if not project_ids:
            return []
        if self._freshness is not None:
            await self._freshness.ensure_fresh(project_ids=project_ids, organization_id=dataset.organization_id)

        root = LineageRef.dataset_field(dataset.id, field_id)
        depth = max(1, min(int(max_depth), MAX_DEPTH_LIMIT))
        lineages = await self._projections.load_lineage_many(project_ids)
        result: list[FieldDependent] = []
        for project_id in project_ids:
            lineage = lineages.get(project_id)
            if lineage is None:
                continue
            result.extend(collect_dependents(index_lineage(project_id, lineage), root, max_depth=depth))
        return result
