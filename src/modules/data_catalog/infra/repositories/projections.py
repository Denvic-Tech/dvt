from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import ProjectCatalogProjection, ProjectionRepository
from ..catalog_mappers import apply_projection, projection_to_domain
from ..db_models import ProjectCatalogProjectionRecord


class SQLAlchemyProjectionRepository(ProjectionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, project_id: str) -> ProjectCatalogProjection | None:
        record = await self._session.get(ProjectCatalogProjectionRecord, project_id)
        return projection_to_domain(record) if record is not None else None

    async def get_many(self, project_ids: Sequence[str]) -> dict[str, ProjectCatalogProjection]:
        if not project_ids:
            return {}
        statement = sa.select(ProjectCatalogProjectionRecord).where(
            ProjectCatalogProjectionRecord.project_id.in_(list(project_ids))
        )
        records = (await self._session.execute(statement)).scalars().all()
        return {record.project_id: projection_to_domain(record) for record in records}

    async def save(self, projection: ProjectCatalogProjection) -> None:
        record = await self._session.get(ProjectCatalogProjectionRecord, projection.project_id)
        if record is None:
            record = ProjectCatalogProjectionRecord(
                project_id=projection.project_id,
                organization_id=projection.organization_id,
            )
            apply_projection(record, projection)
            self._session.add(record)
        else:
            apply_projection(record, projection)
        await self._session.flush()
