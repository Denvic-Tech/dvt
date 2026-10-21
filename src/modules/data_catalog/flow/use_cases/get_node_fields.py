"""Колонки DataFrame-порта ноды с происхождением и наследованными описаниями."""

from __future__ import annotations

from collections.abc import Mapping

from ...domain import (
    DatasetField,
    DatasetFieldRepository,
    LineageNodePortNotFoundError,
    LineageRef,
    LineageTextRenderer,
    NodeFieldsResult,
    NodeFieldView,
    PortLineage,
    ProjectionRepository,
)
from ...domain.policies import DescriptionResolver, LineageIndex, index_lineage
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


def select_port(ports: list[PortLineage], port: str | None) -> PortLineage | None:
    if port is not None:
        for item in ports:
            if item.port == port:
                return item
        return None
    outputs = [item for item in ports if item.role == "output"]
    candidates = outputs or ports
    return candidates[0] if candidates else None


class GetNodeFields:
    def __init__(
        self,
        *,
        projections: ProjectionRepository,
        fields: DatasetFieldRepository,
        renderer: LineageTextRenderer,
        freshness: ProjectionFreshnessProvider | None = None,
    ) -> None:
        self._projections = projections
        self._fields = fields
        self._renderer = renderer
        self._freshness = freshness

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

        resolver = DescriptionResolver(index, await load_field_lookup(self._fields, index))
        views = tuple(self._view(selected, column_ref, resolver, locale) for column_ref in selected.names)
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
        )

    def _view(self, port: PortLineage, name: str, resolver: DescriptionResolver, locale: str) -> NodeFieldView:
        column = port.column(name)
        assert column is not None
        ref = port.ref(name)
        description = resolver.resolve(ref)
        return NodeFieldView(
            name=name,
            ref=ref,
            op=column.op,
            origin=column.origin or ref,
            deps=column.deps,
            deps_unknown=column.deps_unknown,
            description=description.text,
            provenance=description.provenance,
            description_source=description.source,
            explanation=self._renderer.render(str(column.details.get("template", "")), _params(column.details), locale),
        )


def _params(details: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in details.items() if key != "template"}
