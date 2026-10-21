"""Объяснение колонки ноды: путь к источникам или к потребителям внутри проекта."""

from __future__ import annotations

from collections.abc import Mapping

from ...domain import (
    DatasetFieldRepository,
    ExplainDirection,
    FieldExplanation,
    LineageColumnNotFoundError,
    LineageNodePortNotFoundError,
    LineageRef,
    LineageTextRenderer,
    ProjectionRepository,
)
from ...domain.policies import DescriptionResolver, explain, index_lineage
from ..providers import ProjectionFreshnessProvider
from .get_node_fields import load_field_lookup, select_port

DEFAULT_MAX_DEPTH = 20
MAX_DEPTH_LIMIT = 100


class ExplainField:
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
        column: str,
        port: str | None = None,
        direction: ExplainDirection = ExplainDirection.UPSTREAM,
        max_depth: int = DEFAULT_MAX_DEPTH,
        locale: str = "en",
    ) -> FieldExplanation:
        if self._freshness is not None:
            await self._freshness.ensure_fresh(project_ids=[project_id], organization_id=organization_id)
        lineage = await self._projections.load_lineage(project_id)
        if lineage is None:
            raise LineageNodePortNotFoundError(f"Project {project_id} has no lineage yet")
        index = index_lineage(project_id, lineage)
        selected = select_port(index.node_ports(node_id), port)
        if selected is None:
            raise LineageNodePortNotFoundError(f"Node {node_id} port {port or '*'} is not part of the lineage")
        if selected.column(column) is None:
            raise LineageColumnNotFoundError(f"Column {column!r} is not on port {selected.port} of node {node_id}")

        fields = await load_field_lookup(self._fields, index)
        root: LineageRef = selected.ref(column)
        depth = max(1, min(int(max_depth), MAX_DEPTH_LIMIT))
        explanation = explain(
            index,
            root,
            direction=direction,
            max_depth=depth,
            render=lambda details: self._render(details, locale),
            fields=fields,
        )
        description = DescriptionResolver(index, fields).resolve(root)
        return FieldExplanation(
            root=explanation.root,
            direction=explanation.direction,
            steps=explanation.steps,
            gaps=explanation.gaps,
            description=description,
            truncated=explanation.truncated,
        )

    def _render(self, details: Mapping[str, object], locale: str) -> str | None:
        template = str(details.get("template", ""))
        if not template:
            return None
        params = {key: value for key, value in details.items() if key != "template"}
        return self._renderer.render(template, params, locale)
