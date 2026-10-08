from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.project.infra.db_models import ProjectRecord

from ...domain import (
    CatalogViewer,
    DatasetLink,
    DatasetLinkRepository,
    DatasetUsageEntry,
    LinkDirection,
    LinkKind,
    ResolvedVia,
)
from ..catalog_mappers import aware, link_to_record
from ..db_models import DatasetLinkRecord
from .visibility import project_visibility_filters


class SQLAlchemyDatasetLinkRepository(DatasetLinkRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_for_project(self, project_id: str, links: Sequence[DatasetLink]) -> None:
        await self._session.execute(
            sa.delete(DatasetLinkRecord).where(DatasetLinkRecord.project_id == project_id)
        )
        for link in links:
            self._session.add(link_to_record(link))
        await self._session.flush()

    async def list_usage(
        self,
        dataset_id: str,
        viewer: CatalogViewer,
        direction: LinkDirection | None = None,
    ) -> list[DatasetUsageEntry]:
        filters = [DatasetLinkRecord.dataset_id == dataset_id, *project_visibility_filters(viewer)]
        if direction is not None:
            filters.append(DatasetLinkRecord.direction == direction.value)
        statement = (
            sa.select(DatasetLinkRecord, ProjectRecord.name)
            .join(ProjectRecord, ProjectRecord.id == DatasetLinkRecord.project_id)
            .where(*filters)
            .order_by(ProjectRecord.name, DatasetLinkRecord.node_id, DatasetLinkRecord.direction)
        )
        rows = (await self._session.execute(statement)).all()
        return [
            DatasetUsageEntry(
                project_id=record.project_id,
                project_name=project_name,
                node_id=record.node_id,
                node_name=record.node_name,
                direction=LinkDirection(record.direction),
                kind=LinkKind(record.kind),
                resolved_via=ResolvedVia(record.resolved_via),
                graph_revision=record.graph_revision,
                updated_at=aware(record.updated_at),
            )
            for record, project_name in rows
        ]

    async def list_project_ids(self, dataset_id: str, viewer: CatalogViewer) -> list[str]:
        statement = (
            sa.select(DatasetLinkRecord.project_id)
            .join(ProjectRecord, ProjectRecord.id == DatasetLinkRecord.project_id)
            .where(DatasetLinkRecord.dataset_id == dataset_id, *project_visibility_filters(viewer))
            .distinct()
        )
        return list((await self._session.execute(statement)).scalars().all())

    async def find_dataset_ids(
        self,
        project_id: str,
        node_id: str,
        direction: LinkDirection,
    ) -> list[str]:
        statement = (
            sa.select(DatasetLinkRecord.dataset_id)
            .where(
                DatasetLinkRecord.project_id == project_id,
                DatasetLinkRecord.node_id == node_id,
                DatasetLinkRecord.direction == direction.value,
            )
            .distinct()
        )
        return list((await self._session.execute(statement)).scalars().all())
