"""Все колонки проекта группами по origin: обзор для окна каталога и для агента."""

from __future__ import annotations

from ...domain import (
    Dataset,
    DatasetFieldRepository,
    DatasetRepository,
    NodeColumnAnnotationRepository,
    ProjectColumnsResult,
    ProjectionRepository,
)
from ...domain.policies import (
    DescriptionResolver,
    LineageIndex,
    build_column_rows,
    collect_orphaned_annotations,
    collect_unresolved_ports,
    group_columns_by_origin,
    index_lineage,
)
from ..providers import ProjectionFreshnessProvider
from .get_node_fields import load_annotation_lookup, load_field_lookup


class GetProjectColumns:
    def __init__(
        self,
        *,
        projections: ProjectionRepository,
        fields: DatasetFieldRepository,
        datasets: DatasetRepository,
        annotations: NodeColumnAnnotationRepository,
        freshness: ProjectionFreshnessProvider | None = None,
    ) -> None:
        self._projections = projections
        self._fields = fields
        self._datasets = datasets
        self._annotations = annotations
        self._freshness = freshness

    async def execute(self, *, project_id: str, organization_id: str | None) -> ProjectColumnsResult:
        if self._freshness is not None:
            await self._freshness.ensure_fresh(project_ids=[project_id], organization_id=organization_id)
        lineage = await self._projections.load_lineage(project_id)
        if lineage is None:
            # Проекции нет даже после repair: окно показывает пустой каталог, а не ошибку.
            return ProjectColumnsResult(project_id=project_id, lineage_available=False)

        index = index_lineage(project_id, lineage)
        fields = await load_field_lookup(self._fields, index)
        annotations = await load_annotation_lookup(self._annotations, project_id)
        datasets = await self._load_origin_datasets(index)
        resolver = DescriptionResolver(index, fields, annotations)
        groups = group_columns_by_origin(
            index, resolver, fields=fields, datasets=datasets, annotations=annotations
        )
        return ProjectColumnsResult(
            project_id=project_id,
            groups=groups,
            rows=build_column_rows(groups),
            unresolved_ports=collect_unresolved_ports(lineage),
            orphaned_annotations=collect_orphaned_annotations(index, annotations),
            lineage_available=True,
            truncated=lineage.truncated,
        )

    async def _load_origin_datasets(self, index: LineageIndex) -> dict[str, Dataset]:
        dataset_ids: dict[str, None] = {}
        for _, column in index.columns.values():
            origin = column.origin
            if origin is not None and origin.is_dataset_field and origin.dataset_id:
                dataset_ids.setdefault(origin.dataset_id, None)
        result: dict[str, Dataset] = {}
        for dataset_id in dataset_ids:
            dataset = await self._datasets.get(dataset_id)
            if dataset is not None:
                result[dataset_id] = dataset
        return result
