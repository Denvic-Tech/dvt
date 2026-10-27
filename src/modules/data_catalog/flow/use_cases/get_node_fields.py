"""Колонки DataFrame-порта ноды с происхождением и наследованными описаниями."""

from __future__ import annotations

from collections.abc import Mapping

from ...domain import (
    Dataset,
    DatasetField,
    DatasetFieldRepository,
    DatasetRepository,
    LineageNodePortNotFoundError,
    LineageRef,
    LineageTextRenderer,
    NodeColumnAnnotation,
    NodeColumnAnnotationRepository,
    NodeFieldsResult,
    NodeFieldView,
    PortLineage,
    ProjectionRepository,
)
from ...domain.policies import (
    DescriptionResolver,
    LineageIndex,
    description_attribution,
    index_lineage,
)
from ..providers import ProjectionFreshnessProvider


async def load_field_lookup(
    fields: DatasetFieldRepository,
    index: LineageIndex,
) -> dict[str, DatasetField]:
    """`ds:<dataset_id>:<field_id>` → поле для всех сущностей, на которые ссылается lineage."""
    dataset_ids = sorted(index.dataset_ids())
    if not dataset_ids:
        return {}
    by_dataset = await fields.list_for_datasets(dataset_ids)
    return {
        LineageRef.dataset_field(dataset_id, item.id).key: item
        for dataset_id, items in by_dataset.items()
        for item in items
    }


async def load_annotation_lookup(
    annotations: NodeColumnAnnotationRepository | None,
    project_id: str,
) -> dict[str, NodeColumnAnnotation]:
    """`node:<node_id>:<port>:<column>` → аннотация; без репозитория аннотаций нет."""
    if annotations is None:
        return {}
    return {item.ref.key: item for item in await annotations.list_for_project(project_id)}


DEFAULT_OUTPUT_PORT = "output"


def select_port(ports: list[PortLineage], port: str | None) -> PortLineage | None:
    """Без явного порта берётся основной выход: `output`, если он есть, иначе первый выход.

    Порты в документе lineage отсортированы по имени, поэтому у нод с несколькими выходами
    (`inverted_output` у фильтра) первый по алфавиту не является основным.
    """
    if port is not None:
        for item in ports:
            if item.port == port:
                return item
        return None
    outputs = [item for item in ports if item.role == "output"]
    candidates = outputs or ports
    for item in candidates:
        if item.port == DEFAULT_OUTPUT_PORT:
            return item
    return candidates[0] if candidates else None


class GetNodeFields:
    def __init__(
        self,
        *,
        projections: ProjectionRepository,
        fields: DatasetFieldRepository,
        renderer: LineageTextRenderer,
        freshness: ProjectionFreshnessProvider | None = None,
        annotations: NodeColumnAnnotationRepository | None = None,
        datasets: DatasetRepository | None = None,
    ) -> None:
        self._projections = projections
        self._fields = fields
        self._renderer = renderer
        self._freshness = freshness
        self._annotations = annotations
        self._datasets = datasets

    async def execute(
        self,
        *,
        project_id: str,
        organization_id: str | None,
        node_id: str,
        port: str | None = None,
        locale: str = "en",
    ) -> NodeFieldsResult:
        if self._freshness is not None:
            await self._freshness.ensure_fresh(project_ids=[project_id], organization_id=organization_id)
        lineage = await self._projections.load_lineage(project_id)
        if lineage is None:
            raise LineageNodePortNotFoundError(f"Project {project_id} has no lineage yet")
        index = index_lineage(project_id, lineage)
        ports = index.node_ports(node_id)
        selected = select_port(ports, port)
        if selected is None:
            raise LineageNodePortNotFoundError(
                f"Node {node_id} port {port or '*'} is not part of project {project_id} lineage"
            )

        fields = await load_field_lookup(self._fields, index)
        annotations = await load_annotation_lookup(self._annotations, project_id)
        resolver = DescriptionResolver(index, fields, annotations)
        datasets = await self._load_origin_datasets(selected, fields)
        views = tuple(
            self._view(selected, name, resolver, locale, fields, annotations, datasets)
            for name in selected.names
        )
        orphaned = tuple(
            item
            for item in annotations.values()
            if item.node_id == selected.node_id
            and item.port == selected.port
            and item.column not in selected.names
        )
        return NodeFieldsResult(
            project_id=project_id,
            node_id=selected.node_id,
            node_name=selected.node_name,
            port=selected.port,
            role=selected.role,
            status=selected.status,
            reason=selected.reason,
            detail=selected.detail,
            fields=views,
            available_ports=tuple(item.port for item in ports),
            orphaned_annotations=orphaned,
        )

    async def _load_origin_datasets(
        self,
        port: PortLineage,
        fields: Mapping[str, DatasetField],
    ) -> dict[str, Dataset]:
        """Сущности, из полей которых происходят колонки порта: для `origin_location`."""
        if self._datasets is None:
            return {}
        dataset_ids: dict[str, None] = {}
        for column in port.columns:
            origin = column.origin
            if origin is not None and origin.is_dataset_field and origin.key in fields:
                dataset_ids.setdefault(origin.dataset_id or "", None)
        result: dict[str, Dataset] = {}
        for dataset_id in dataset_ids:
            dataset = await self._datasets.get(dataset_id)
            if dataset is not None:
                result[dataset_id] = dataset
        return result

    def _view(
        self,
        port: PortLineage,
        name: str,
        resolver: DescriptionResolver,
        locale: str,
        fields: Mapping[str, DatasetField],
        annotations: Mapping[str, NodeColumnAnnotation],
        datasets: Mapping[str, Dataset],
    ) -> NodeFieldView:
        column = port.column(name)
        assert column is not None
        ref = port.ref(name)
        description = resolver.resolve(ref)
        origin = column.origin or ref
        origin_field = fields.get(origin.key) if origin.is_dataset_field else None
        origin_dataset = datasets.get(origin.dataset_id or "") if origin_field is not None else None
        updated_by, updated_at = description_attribution(description, fields, annotations)
        return NodeFieldView(
            name=name,
            ref=ref,
            op=column.op,
            origin=origin,
            deps=column.deps,
            deps_unknown=column.deps_unknown,
            description=description.text,
            provenance=description.provenance,
            description_source=description.source,
            explanation=self._renderer.render(str(column.details.get("template", "")), _params(column.details), locale),
            description_updated_by=updated_by,
            description_updated_at=updated_at,
            origin_field_name=origin_field.name if origin_field is not None else None,
            origin_location=origin_dataset.location if origin_dataset is not None else None,
        )


def _params(details: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in details.items() if key != "template"}
