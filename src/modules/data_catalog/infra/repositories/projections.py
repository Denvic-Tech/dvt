from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from ...domain import ProjectCatalogProjection, ProjectionRepository, ProjectLineage
from ..catalog_mappers import apply_projection, projection_to_domain
from ..db_models import PROJECTION_LINEAGE_COLUMN, DatasetLinkRecord, ProjectCatalogProjectionRecord
from ..lineage_mappers import lineage_from_json, lineage_to_json

_PROJECTIONS = ProjectCatalogProjectionRecord.__table__


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

    async def save_lineage(self, project_id: str, lineage: ProjectLineage | None) -> None:
        # Колонка lineage не маппится на атрибут записи: документ большой и грузится только явно.
        await self._session.execute(
            sa.update(_PROJECTIONS)
            .where(_PROJECTIONS.c.project_id == project_id)
            .values({PROJECTION_LINEAGE_COLUMN: lineage_to_json(lineage) if lineage is not None else None})
        )

    async def load_lineage(self, project_id: str) -> ProjectLineage | None:
        loaded = await self.load_lineage_many([project_id])
        return loaded.get(project_id)

    async def load_lineage_many(self, project_ids: Sequence[str]) -> dict[str, ProjectLineage]:
        if not project_ids:
            return {}
        column = _PROJECTIONS.c[PROJECTION_LINEAGE_COLUMN]
        rows = (
            await self._session.execute(
                sa.select(_PROJECTIONS.c.project_id, column).where(
                    _PROJECTIONS.c.project_id.in_(list(project_ids)),
                    column.is_not(None),
                )
            )
        ).all()
        result: dict[str, ProjectLineage] = {}
        for project_id, payload in rows:
            lineage = lineage_from_json(payload)
            if lineage is not None:
                result[project_id] = lineage
        return result

    async def mark_stale_for_project(self, project_id: str) -> bool:
        outcome = await self._session.execute(
            sa.update(_PROJECTIONS)
            .where(_PROJECTIONS.c.project_id == project_id, _PROJECTIONS.c.lineage_schema_version != 0)
            .values(lineage_schema_version=0)
        )
        return bool(outcome.rowcount)

    async def mark_stale_for_dataset(self, dataset_id: str) -> int:
        consumers = sa.select(DatasetLinkRecord.project_id).where(DatasetLinkRecord.dataset_id == dataset_id)
        outcome = await self._session.execute(
            sa.update(_PROJECTIONS)
            .where(_PROJECTIONS.c.project_id.in_(consumers), _PROJECTIONS.c.lineage_schema_version != 0)
            .values(lineage_schema_version=0)
        )
        return int(outcome.rowcount or 0)
