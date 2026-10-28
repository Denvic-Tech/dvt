from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import NodePortObservationRepository, ObservedPortSchema
from ..catalog_mappers import (
    apply_port_observation,
    port_observation_to_domain,
    port_observation_to_record,
)
from ..db_models import NodePortObservationRecord


class SQLAlchemyNodePortObservationRepository(NodePortObservationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_project(self, project_id: str) -> list[ObservedPortSchema]:
        statement = (
            sa.select(NodePortObservationRecord)
            .where(NodePortObservationRecord.project_id == project_id)
            .order_by(NodePortObservationRecord.node_id, NodePortObservationRecord.port)
        )
        records = (await self._session.execute(statement)).scalars().all()
        return [port_observation_to_domain(record) for record in records]

    async def list_for_node(self, project_id: str, node_id: str) -> list[ObservedPortSchema]:
        statement = (
            sa.select(NodePortObservationRecord)
            .where(
                NodePortObservationRecord.project_id == project_id,
                NodePortObservationRecord.node_id == node_id,
            )
            .order_by(NodePortObservationRecord.port)
        )
        records = (await self._session.execute(statement)).scalars().all()
        return [port_observation_to_domain(record) for record in records]

    async def upsert_many(self, observations: Sequence[ObservedPortSchema]) -> None:
        if not observations:
            return
        project_id = observations[0].project_id
        node_ids = list({item.node_id for item in observations})
        existing = {
            (record.node_id, record.port): record
            for record in (
                await self._session.execute(
                    sa.select(NodePortObservationRecord).where(
                        NodePortObservationRecord.project_id == project_id,
                        NodePortObservationRecord.node_id.in_(node_ids),
                    )
                )
            ).scalars()
        }
        for item in observations:
            record = existing.get((item.node_id, item.port))
            if record is None:
                self._session.add(port_observation_to_record(item))
            else:
                apply_port_observation(record, item)
        await self._session.flush()
