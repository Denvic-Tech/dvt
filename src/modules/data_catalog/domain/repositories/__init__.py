"""Контракты репозиториев каталога. Реализации живут в infra."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from ..catalog_values import CatalogViewer
from ..entities import (
    Dataset,
    DatasetConnection,
    DatasetField,
    DatasetLink,
    DatasetSearchPage,
    DatasetSearchQuery,
    DatasetUsageEntry,
    ProjectCatalogProjection,
)
from ..lineage import NodeColumnAnnotation, ProjectLineage
from ..types import LinkDirection


class DatasetRepository(Protocol):
    async def get(self, dataset_id: str) -> Dataset | None: ...

    async def get_visible(self, dataset_id: str, viewer: CatalogViewer) -> Dataset | None: ...

    async def get_by_physical_key(self, organization_id: str, physical_key: str) -> Dataset | None: ...

    async def upsert(self, dataset: Dataset) -> Dataset:
        """Вставляет сущность или возвращает уже существующую с тем же (org, physical_key)."""
        ...

    async def update(self, dataset: Dataset) -> Dataset: ...

    async def search(self, viewer: CatalogViewer, query: DatasetSearchQuery) -> DatasetSearchPage: ...


class DatasetFieldRepository(Protocol):
    async def list_for_dataset(self, dataset_id: str) -> list[DatasetField]: ...

    async def save_many(self, fields: Sequence[DatasetField]) -> None: ...

    async def delete(self, field_id: str) -> None:
        """Единственное физическое удаление: дубликат-наблюдение после подтверждения переименования."""
        ...

    async def list_for_datasets(self, dataset_ids: Sequence[str]) -> dict[str, list[DatasetField]]:
        """Поля нескольких сущностей одним запросом; ключ — dataset_id."""
        ...


class DatasetConnectionRepository(Protocol):
    async def touch(
        self,
        dataset_id: str,
        connection_id: str,
        revision: str,
        seen_at: datetime,
    ) -> None: ...

    async def list_for_dataset(self, dataset_id: str) -> list[DatasetConnection]: ...

    async def list_usable_connection_ids(
        self,
        dataset_id: str,
        viewer: CatalogViewer,
    ) -> list[str]:
        """Connection'ы сущности, которыми viewer вправе пользоваться (не удалённые)."""
        ...


class DatasetLinkRepository(Protocol):
    async def replace_for_project(self, project_id: str, links: Sequence[DatasetLink]) -> None: ...

    async def list_usage(
        self,
        dataset_id: str,
        viewer: CatalogViewer,
        direction: LinkDirection | None = None,
    ) -> list[DatasetUsageEntry]: ...

    async def list_project_ids(self, dataset_id: str, viewer: CatalogViewer) -> list[str]: ...

    async def find_dataset_ids(
        self,
        project_id: str,
        node_id: str,
        direction: LinkDirection,
    ) -> list[str]:
        """Сущности, к которым нода проекта привязана статическим проходом (без фильтра видимости)."""
        ...


class NodeColumnAnnotationRepository(Protocol):
    async def list_for_project(self, project_id: str) -> list[NodeColumnAnnotation]: ...

    async def upsert_many(self, annotations: Sequence[NodeColumnAnnotation]) -> None: ...

    async def delete_many(self, annotation_ids: Sequence[str]) -> None: ...


class ProjectionRepository(Protocol):
    async def get(self, project_id: str) -> ProjectCatalogProjection | None: ...

    async def get_many(self, project_ids: Sequence[str]) -> dict[str, ProjectCatalogProjection]: ...

    async def save(self, projection: ProjectCatalogProjection) -> None: ...

    async def save_lineage(self, project_id: str, lineage: ProjectLineage | None) -> None:
        """Заменяет документ lineage проекции; None очищает его."""
        ...

    async def load_lineage(self, project_id: str) -> ProjectLineage | None: ...

    async def load_lineage_many(self, project_ids: Sequence[str]) -> dict[str, ProjectLineage]: ...

    async def mark_stale_for_dataset(self, dataset_id: str) -> int:
        """Сбрасывает версию семантики проекций проектов, читающих сущность; возвращает их число."""
        ...
