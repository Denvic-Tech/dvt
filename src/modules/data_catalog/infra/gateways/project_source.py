"""Выбор проектов для сверки проекций: один запрос по projects с outer join на проекции."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.project.infra.db_models import ProjectRecord

from ...domain import CatalogProjectSource, ProjectRef
from ..db_models import ProjectCatalogProjectionRecord


class SQLAlchemyCatalogProjectSource(CatalogProjectSource):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_projects(
        self,
        *,
        lineage_schema_version: int,
        stale_only: bool,
        after_project_id: str | None,
        limit: int,
        organization_id: str | None = None,
        project_ids: Sequence[str] | None = None,
    ) -> list[ProjectRef]:
        projection = ProjectCatalogProjectionRecord
        statement = (
            sa.select(ProjectRecord.id, ProjectRecord.organization_id)
            .outerjoin(projection, projection.project_id == ProjectRecord.id)
            .where(ProjectRecord.is_deleted.is_(False))
            .order_by(ProjectRecord.id)
            .limit(limit)
        )
        if stale_only:
            statement = statement.where(
                sa.or_(
                    projection.project_id.is_(None),
                    projection.lineage_schema_version < lineage_schema_version,
                    projection.graph_revision != ProjectRecord.graph_revision,
                )
            )
        if after_project_id is not None:
            statement = statement.where(ProjectRecord.id > after_project_id)
        if organization_id is not None:
            statement = statement.where(ProjectRecord.organization_id == organization_id)
        if project_ids is not None:
            if not project_ids:
                return []
            statement = statement.where(ProjectRecord.id.in_(list(project_ids)))
        rows = (await self._session.execute(statement)).all()
        return [ProjectRef(project_id=row[0], organization_id=row[1]) for row in rows]
