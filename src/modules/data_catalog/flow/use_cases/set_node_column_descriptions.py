"""Описания колонок порта ноды: запись и удаление аннотаций внутри проекта."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from ...domain import (
    OUTPUT_ROLE,
    ColumnDescriptionChange,
    LineageNodePortNotFoundError,
    LineageRef,
    NodeColumnAnnotation,
    NodeColumnAnnotationRepository,
    NodeColumnDescriptionsResult,
    ProjectGraphGateway,
    ProjectionRepository,
)
from ...domain.policies import LineageIndex, index_lineage, normalize_description
from ..providers import ProjectionFreshnessProvider
from .get_node_fields import select_port


class SetNodeColumnDescriptions:
    """Пустое описание удаляет аннотацию; порт по умолчанию берётся из lineage ноды."""

    def __init__(
        self,
        *,
        annotations: NodeColumnAnnotationRepository,
        graph_gateway: ProjectGraphGateway,
        projections: ProjectionRepository,
        freshness: ProjectionFreshnessProvider | None = None,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._annotations = annotations
        self._graph = graph_gateway
        self._projections = projections
        self._freshness = freshness
        self._clock = clock or (lambda: datetime.now(UTC))
        self._id_factory = id_factory or (lambda: str(uuid4()))

    async def execute(
        self,
        *,
        project_id: str,
        organization_id: str | None,
        node_id: str,
        changes: Sequence[ColumnDescriptionChange],
        actor_user_id: str,
        port: str | None = None,
    ) -> NodeColumnDescriptionsResult:
        if not await self._graph.node_exists(project_id, organization_id, node_id):
            raise LineageNodePortNotFoundError(f"Node {node_id} is not part of project {project_id}")

        index = await self._load_index(project_id, organization_id)
        resolved_port = port or self._default_port(index, node_id)
        existing = {
            item.column: item
            for item in await self._annotations.list_for_project(project_id)
            if item.node_id == node_id and item.port == resolved_port
        }

        now = self._clock()
        upserts: dict[str, NodeColumnAnnotation] = {}
        removed: dict[str, str] = {}
        for change in changes:
            column = change.column.strip()
            if not column:
                continue
            text = normalize_description(change.description)
            current = existing.get(column)
            if text is None:
                upserts.pop(column, None)
                if current is not None:
                    removed[column] = current.id
                continue
            removed.pop(column, None)
            origin_key = self._origin_key(index, node_id, resolved_port, column)
            if current is not None:
                current.description = text
                current.origin_key = origin_key
                current.description_updated_by = actor_user_id
                current.updated_at = now
                upserts[column] = current
            else:
                upserts[column] = NodeColumnAnnotation(
                    id=self._id_factory(),
                    project_id=project_id,
                    node_id=node_id,
                    port=resolved_port,
                    column=column,
                    description=text,
                    created_at=now,
                    updated_at=now,
                    origin_key=origin_key,
                    description_updated_by=actor_user_id,
                )

        if removed:
            await self._annotations.delete_many(list(removed.values()))
        if upserts:
            await self._annotations.upsert_many(list(upserts.values()))
        return NodeColumnDescriptionsResult(
            node_id=node_id,
            port=resolved_port,
            annotations=tuple(upserts.values()),
            removed_columns=tuple(removed),
        )

    async def _load_index(self, project_id: str, organization_id: str | None) -> LineageIndex | None:
        if self._freshness is not None:
            await self._freshness.ensure_fresh(project_ids=[project_id], organization_id=organization_id)
        lineage = await self._projections.load_lineage(project_id)
        return index_lineage(project_id, lineage) if lineage is not None else None

    @staticmethod
    def _default_port(index: LineageIndex | None, node_id: str) -> str:
        selected = select_port(index.node_ports(node_id), None) if index is not None else None
        return selected.port if selected is not None else OUTPUT_ROLE

    @staticmethod
    def _origin_key(index: LineageIndex | None, node_id: str, port: str, column: str) -> str | None:
        if index is None:
            return None
        ref = LineageRef.node_column(node_id, port, column)
        found = index.column(ref)
        if found is None:
            return None
        return (found[1].origin or ref).key
