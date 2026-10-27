"""In-memory реализации доменных контрактов для тестов use cases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from src.modules.data_catalog.domain import (
    CatalogViewer,
    ConnectionLocator,
    Dataset,
    DatasetConnection,
    DatasetField,
    DatasetLink,
    DatasetSearchHit,
    DatasetSearchPage,
    DatasetSearchQuery,
    DatasetUsageEntry,
    ExpressionUnresolvedError,
    LinkDirection,
    NodeColumnAnnotation,
    ObservedField,
    ProjectCatalogProjection,
    ProjectGraphSnapshot,
    ProjectStampSource,
    SchemaActor,
    SchemaSourceUnavailableError,
    SqlReferenceExtractionError,
    SqlTableRef,
    SqlTableReferences,
)


class InMemoryDatasetRepository:
    def __init__(self) -> None:
        self.items: dict[str, Dataset] = {}

    async def get(self, dataset_id: str) -> Dataset | None:
        return self.items.get(dataset_id)

    async def get_visible(self, dataset_id: str, viewer: CatalogViewer) -> Dataset | None:
        return self.items.get(dataset_id)

    async def get_by_physical_key(self, organization_id: str, physical_key: str) -> Dataset | None:
        for item in self.items.values():
            if item.organization_id == organization_id and item.physical_key == physical_key:
                return item
        return None

    async def upsert(self, dataset: Dataset) -> Dataset:
        existing = await self.get_by_physical_key(dataset.organization_id, dataset.physical_key)
        if existing is not None:
            return existing
        self.items[dataset.id] = dataset
        return dataset

    async def update(self, dataset: Dataset) -> Dataset:
        self.items[dataset.id] = dataset
        return dataset

    async def search(self, viewer: CatalogViewer, query: DatasetSearchQuery) -> DatasetSearchPage:
        hits = tuple(
            DatasetSearchHit(dataset=item, field_count=0, reader_count=0, writer_count=0)
            for item in self.items.values()
        )
        return DatasetSearchPage(items=hits[: query.limit])


class InMemoryFieldRepository:
    def __init__(self) -> None:
        self.items: dict[str, DatasetField] = {}

    async def list_for_dataset(self, dataset_id: str) -> list[DatasetField]:
        return [item for item in self.items.values() if item.dataset_id == dataset_id]

    async def save_many(self, fields: Sequence[DatasetField]) -> None:
        for item in fields:
            self.items[item.id] = item

    async def delete(self, field_id: str) -> None:
        self.items.pop(field_id, None)
        self.deleted = [*getattr(self, "deleted", []), field_id]

    async def list_for_datasets(self, dataset_ids: Sequence[str]) -> dict[str, list[DatasetField]]:
        return {dataset_id: await self.list_for_dataset(dataset_id) for dataset_id in dataset_ids}


class InMemoryConnectionRepository:
    def __init__(self, usable: Sequence[str] = ()) -> None:
        self.touched: list[tuple[str, str, str]] = []
        self.usable = list(usable)

    async def touch(self, dataset_id: str, connection_id: str, revision: str, seen_at: datetime) -> None:
        self.touched.append((dataset_id, connection_id, revision))

    async def list_for_dataset(self, dataset_id: str) -> list[DatasetConnection]:
        return [
            DatasetConnection(dataset_id, connection_id, revision, datetime.min, datetime.min)
            for (ds, connection_id, revision) in self.touched
            if ds == dataset_id
        ]

    async def list_usable_connection_ids(self, dataset_id: str, viewer: CatalogViewer) -> list[str]:
        return list(self.usable)


class InMemoryLinkRepository:
    def __init__(self) -> None:
        self.by_project: dict[str, list[DatasetLink]] = {}

    async def replace_for_project(self, project_id: str, links: Sequence[DatasetLink]) -> None:
        self.by_project[project_id] = list(links)

    async def list_usage(
        self, dataset_id: str, viewer: CatalogViewer, direction: LinkDirection | None = None
    ) -> list[DatasetUsageEntry]:
        return [
            DatasetUsageEntry(
                project_id=link.project_id,
                project_name=None,
                node_id=link.node_id,
                node_name=link.node_name,
                direction=link.direction,
                kind=link.kind,
                resolved_via=link.resolved_via,
                graph_revision=link.graph_revision,
                updated_at=link.updated_at,
            )
            for links in self.by_project.values()
            for link in links
            if link.dataset_id == dataset_id and (direction is None or link.direction is direction)
        ]

    async def list_project_ids(self, dataset_id: str, viewer: CatalogViewer) -> list[str]:
        return sorted(
            {
                link.project_id
                for links in self.by_project.values()
                for link in links
                if link.dataset_id == dataset_id
            }
        )

    async def find_dataset_ids(self, project_id: str, node_id: str, direction: LinkDirection) -> list[str]:
        return [
            link.dataset_id
            for link in self.by_project.get(project_id, [])
            if link.node_id == node_id and link.direction is direction
        ]


class InMemoryProjectionRepository:
    def __init__(self) -> None:
        self.items: dict[str, ProjectCatalogProjection] = {}
        self.fail_on_save = False

    async def get(self, project_id: str) -> ProjectCatalogProjection | None:
        return self.items.get(project_id)

    async def get_many(self, project_ids: Sequence[str]) -> dict[str, ProjectCatalogProjection]:
        return {pid: self.items[pid] for pid in project_ids if pid in self.items}

    async def save(self, projection: ProjectCatalogProjection) -> None:
        if self.fail_on_save:
            raise RuntimeError("storage unavailable")
        self.items[projection.project_id] = projection

    async def save_lineage(self, project_id: str, lineage) -> None:
        self.lineage = getattr(self, "lineage", {})
        if lineage is None:
            self.lineage.pop(project_id, None)
        else:
            self.lineage[project_id] = lineage

    async def load_lineage(self, project_id: str):
        return getattr(self, "lineage", {}).get(project_id)

    async def load_lineage_many(self, project_ids: Sequence[str]):
        stored = getattr(self, "lineage", {})
        return {pid: stored[pid] for pid in project_ids if pid in stored}

    async def mark_stale_for_dataset(self, dataset_id: str) -> int:
        self.stale_marks = [*getattr(self, "stale_marks", []), dataset_id]
        return 1


class InMemoryAnnotationRepository:
    def __init__(self) -> None:
        self.items: dict[str, NodeColumnAnnotation] = {}

    async def list_for_project(self, project_id: str) -> list[NodeColumnAnnotation]:
        return [item for item in self.items.values() if item.project_id == project_id]

    async def upsert_many(self, annotations: Sequence[NodeColumnAnnotation]) -> None:
        for item in annotations:
            self.items[item.id] = item

    async def delete_many(self, annotation_ids: Sequence[str]) -> None:
        for annotation_id in annotation_ids:
            self.items.pop(annotation_id, None)


class FakeGraphGateway:
    def __init__(self, snapshot: ProjectGraphSnapshot | None, node_ids: Sequence[str] = ()) -> None:
        self.snapshot = snapshot
        self.locks = 0
        self.node_ids = set(node_ids)

    async def node_exists(self, project_id: str, organization_id: str | None, node_id: str) -> bool:
        if node_id in self.node_ids:
            return True
        return self.snapshot is not None and any(node.ui_id == node_id for node in self.snapshot.nodes)

    async def load_stamp_source(self, project_id: str, organization_id: str) -> ProjectStampSource | None:
        return self.snapshot.stamp_source if self.snapshot is not None else None

    async def load_snapshot(self, project_id: str, organization_id: str) -> ProjectGraphSnapshot | None:
        return self.snapshot

    async def lock_project(self, project_id: str, organization_id: str) -> None:
        self.locks += 1


class FakeConnectionLocatorGateway:
    def __init__(self, locators: Mapping[str, ConnectionLocator]) -> None:
        self.locators = dict(locators)

    async def get_locator(self, connection_id: str, organization_id: str) -> ConnectionLocator | None:
        return self.locators.get(connection_id)


class FakeExpressionResolver:
    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        self.values = dict(values or {})

    def resolve(self, expression: str, expression_kind: str, project_variables: Mapping[str, Any]) -> Any:
        if expression in self.values:
            return self.values[expression]
        raise ExpressionUnresolvedError(expression)


class FakeSqlExtractor:
    def __init__(self, tables: Sequence[SqlTableRef] = (), *, fail: str | None = None) -> None:
        self.tables = tuple(tables)
        self.fail = fail

    def extract(self, sql: str, dialect: str, project_variables: Mapping[str, Any]) -> SqlTableReferences:
        if self.fail:
            raise SqlReferenceExtractionError(self.fail)
        return SqlTableReferences(tables=self.tables)


class FakeSchemaSource:
    def __init__(self, fields: Sequence[ObservedField] = (), *, fail: bool = False) -> None:
        self.fields = tuple(fields)
        self.fail = fail
        self.calls: list[str] = []

    async def fetch_fields(self, *, connection_id: str, actor: SchemaActor, locator, bypass_cache=False):
        self.calls.append(connection_id)
        self.locators = [*getattr(self, "locators", []), locator]
        self.bypass_calls = [*getattr(self, "bypass_calls", []), bypass_cache]
        if self.fail:
            raise SchemaSourceUnavailableError("down")
        return self.fields


class FakePortTypeGateway:
    def __init__(self, types: Mapping[str, Any]) -> None:
        self.types = dict(types)

    def get_port_types(self, node_name: str):
        return self.types.get(node_name)


class FakeRenderer:
    def render(self, template_key: str, params: Mapping[str, Any], locale: str) -> str | None:
        return f"{locale}:{template_key}"


class FakeSqlLineageExtractor:
    def __init__(self, result) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def extract(self, sql: str, dialect: str, project_variables: Mapping[str, Any], schema):
        self.calls.append((sql, dialect))
        self.schema = schema
        return self.result


class FakeFreshness:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str | None]] = []

    async def ensure_fresh(self, *, project_ids: Sequence[str], organization_id: str | None) -> list[str]:
        self.calls.append((tuple(project_ids), organization_id))
        return []
