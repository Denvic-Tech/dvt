from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import NodeColumnAnnotation, NodeColumnAnnotationRepository
from ..catalog_mappers import annotation_to_domain, annotation_to_record, apply_annotation
from ..db_models import NodeColumnAnnotationRecord


class SQLAlchemyNodeColumnAnnotationRepository(NodeColumnAnnotationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_project(self, project_id: str) -> list[NodeColumnAnnotation]:
        statement = (
            sa.select(NodeColumnAnnotationRecord)
            .where(NodeColumnAnnotationRecord.project_id == project_id)
            .order_by(
                NodeColumnAnnotationRecord.node_id,
                NodeColumnAnnotationRecord.port,
                NodeColumnAnnotationRecord.column_name,
            )
        )
        records = (await self._session.execute(statement)).scalars().all()
        return [annotation_to_domain(record) for record in records]

    async def upsert_many(self, annotations: Sequence[NodeColumnAnnotation]) -> None:
        if not annotations:
            return
        ids = [item.id for item in annotations]
        existing = {
            record.id: record
            for record in (
                await self._session.execute(
                    sa.select(NodeColumnAnnotationRecord).where(NodeColumnAnnotationRecord.id.in_(ids))
                )
            ).scalars()
        }
        for item in annotations:
            record = existing.get(item.id)
            if record is None:
                self._session.add(annotation_to_record(item))
            else:
                apply_annotation(record, item)
        await self._session.flush()

    async def delete_many(self, annotation_ids: Sequence[str]) -> None:
        unique = list(dict.fromkeys(annotation_ids))
        if not unique:
            return
        await self._session.execute(
            sa.delete(NodeColumnAnnotationRecord).where(NodeColumnAnnotationRecord.id.in_(unique))
        )
        await self._session.flush()
