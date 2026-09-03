from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.project.infra.db_models import ProjectRecord


async def touch_project_updated_at(
    session: AsyncSession,
    *,
    project_id: str,
    organization_id: str,
) -> bool:
    updated_at = datetime.now(tz=UTC)
    result = await session.execute(
        sa.update(ProjectRecord)
        .where(
            ProjectRecord.id == project_id,
            ProjectRecord.organization_id == organization_id,
            ProjectRecord.is_deleted == False,
        )
        .values(updated_at=updated_at)
    )
    return bool(result.rowcount)


async def mark_project_graph_dirty(
    session: AsyncSession,
    *,
    project_id: str,
    organization_id: str,
    node_ids: list[str],
    removed_node_ids: list[str] | None = None,
) -> ProjectRecord | None:
    normalized_node_ids = {node_id for node_id in node_ids if node_id}
    normalized_removed_node_ids = {node_id for node_id in removed_node_ids or [] if node_id}

    project = (
        await session.execute(
            sa.select(ProjectRecord)
            .where(
                ProjectRecord.id == project_id,
                ProjectRecord.organization_id == organization_id,
                ProjectRecord.is_deleted == False,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if project is None:
        return None

    project.dirty_node_ids = sorted(
        ({*(project.dirty_node_ids or [])} - normalized_removed_node_ids)
        | normalized_node_ids
    )
    project.graph_revision = int(project.graph_revision or 0) + 1
    project.updated_at = datetime.now(tz=UTC)
    session.add(project)
    return project


async def clear_project_graph_dirty_if_revision(
    session: AsyncSession,
    *,
    project_id: str,
    graph_revision: int,
    node_ids: list[str] | None = None,
) -> bool:
    project = (
        await session.execute(
            sa.select(ProjectRecord)
            .where(
                ProjectRecord.id == project_id,
                ProjectRecord.is_deleted == False,
                ProjectRecord.graph_revision == graph_revision,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if project is None:
        return False

    if node_ids is None:
        project.dirty_node_ids = []
    else:
        cleared_node_ids = {node_id for node_id in node_ids if node_id}
        project.dirty_node_ids = sorted(
            set(project.dirty_node_ids or []) - cleared_node_ids
        )
    session.add(project)
    return True
