"""Наблюдённый состав колонок выходов ноды: запись и инвалидация проекции при изменении."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from ...domain import (
    NodePortObservationRepository,
    ObservedPortSchema,
    ProjectGraphGateway,
    ProjectionRepository,
)


class RecordObservedPortSchemas:
    """Проекция сбрасывается, только если у какого-то порта изменился набор имён колонок."""

    def __init__(
        self,
        *,
        observations: NodePortObservationRepository,
        projections: ProjectionRepository,
        graph_gateway: ProjectGraphGateway,
    ) -> None:
        self._observations = observations
        self._projections = projections
        self._graph = graph_gateway

    async def execute(self, observations: Sequence[ObservedPortSchema]) -> int:
        if not observations:
            return 0
        project_id = observations[0].project_id
        node_id = observations[0].node_id
        stamp = await self._graph.load_stamp_source(project_id, None)
        revision = stamp.graph_revision if stamp is not None else None

        existing = {
            (item.node_id, item.port): item
            for item in await self._observations.list_for_node(project_id, node_id)
        }
        changed = False
        to_save: list[ObservedPortSchema] = []
        for item in observations:
            current = existing.get((item.node_id, item.port))
            if current is None or current.names != item.names:
                changed = True
            to_save.append(
                item if item.graph_revision is not None else replace(item, graph_revision=revision)
            )
        await self._observations.upsert_many(to_save)
        if changed:
            await self._projections.mark_stale_for_project(project_id)
        return len(to_save)
