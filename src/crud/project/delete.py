from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    AIAnalysisRequestRecord,
    LogRecord,
)
from src.modules.pipeline_graph.infra.db_models import (
    GraphEdgeRecord,
    GraphNodeRecord,
    SubgraphRecord,
)
from src.modules.project.infra.db_models import ProjectRecord, ProjectScheduleRecord
from src.modules.task_execution.infra.db_models import TaskRecord


async def delete_projects_permanently(
    session: AsyncSession,
    *,
    project_ids: Sequence[str],
) -> None:
    normalized_project_ids = tuple(
        dict.fromkeys(project_id for project_id in project_ids if project_id)
    )
    if not normalized_project_ids:
        return

    task_ids = sa.select(TaskRecord.task_id).where(
        TaskRecord.project_id.in_(normalized_project_ids)
    )
    await session.execute(
        sa.update(LogRecord)
        .where(LogRecord.task_id.in_(task_ids))
        .values(task_id=None)
    )
    await session.execute(
        sa.delete(AIAnalysisRequestRecord).where(
            AIAnalysisRequestRecord.project_id.in_(normalized_project_ids)
        )
    )
    await session.execute(
        sa.delete(TaskRecord).where(TaskRecord.project_id.in_(normalized_project_ids))
    )
    await session.execute(
        sa.delete(GraphEdgeRecord).where(GraphEdgeRecord.project_id.in_(normalized_project_ids))
    )
    await session.execute(
        sa.delete(GraphNodeRecord).where(GraphNodeRecord.project_id.in_(normalized_project_ids))
    )
    await session.execute(
        sa.delete(SubgraphRecord).where(SubgraphRecord.project_id.in_(normalized_project_ids))
    )
    await session.execute(
        sa.delete(ProjectScheduleRecord).where(
            ProjectScheduleRecord.project_id.in_(normalized_project_ids)
        )
    )
    await session.execute(
        sa.delete(ProjectRecord).where(ProjectRecord.id.in_(normalized_project_ids))
    )
    await session.flush()
