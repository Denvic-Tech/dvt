from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.pipeline.execution_mode import PipelineExecutionMode

from ..db_models import TaskRecord
from .tasks import TaskReadModel, to_task_read_model


async def get_recent_project_runs_by_project_ids(
    session: AsyncSession,
    *,
    project_ids: Sequence[str],
    organization_id: str | None = None,
    owner_user_id: str | None = None,
    per_project_limit: int = 10,
) -> dict[str, list[TaskReadModel]]:
    """Read-side query for recent full pipeline executions per project."""
    normalized = list(dict.fromkeys(project_id for project_id in project_ids if project_id))
    if not normalized or per_project_limit <= 0:
        return {project_id: [] for project_id in normalized}

    filters: list[sa.ColumnExpressionArgument[bool]] = [
        TaskRecord.project_id.in_(normalized),
        TaskRecord.mode == PipelineExecutionMode.FULL,
    ]
    if organization_id is not None:
        filters.append(TaskRecord.organization_id == organization_id)
    if owner_user_id is not None:
        filters.append(TaskRecord.user_id == owner_user_id)

    row_number = sa.func.row_number().over(
        partition_by=TaskRecord.project_id,
        order_by=(sa.desc(TaskRecord.queued_at), sa.desc(TaskRecord.task_id)),
    ).label("project_run_rank")
    ranked = (
        sa.select(TaskRecord.task_id.label("task_id"), row_number)
        .where(*filters)
        .subquery()
    )
    records = list((await session.execute(
        sa.select(TaskRecord)
        .join(ranked, ranked.c.task_id == TaskRecord.task_id)
        .where(ranked.c.project_run_rank <= per_project_limit)
        .order_by(
            TaskRecord.project_id,
            sa.desc(TaskRecord.queued_at),
            sa.desc(TaskRecord.task_id),
        )
    )).scalars().all())
    grouped = {project_id: [] for project_id in normalized}
    for record in records:
        grouped[record.project_id].append(to_task_read_model(record))
    return grouped
