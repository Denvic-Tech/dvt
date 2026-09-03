import sqlalchemy as sa

from src.db import AsyncSession
from src.models import LogRecord
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord
from src.schemas.http.log import LogEntriesPageSchema, LogEntrySchema

from .common import (
    build_has_more,
    get_project_task_or_404,
)


async def get_project_logs_route_impl(
        *,
        project: ProjectRecord,
        user: UserRecord,
        task_id: str,
        limit: int,
        offset: int,
        session: AsyncSession,
) -> LogEntriesPageSchema:
    await get_project_task_or_404(
        session=session,
        project=project,
        user=user,
        task_id=task_id,
    )

    filters = [
        TaskRecord.project_id == project.id,
        LogRecord.task_id == task_id,
    ]
    join_from = LogRecord.__table__.join(TaskRecord.__table__, LogRecord.task_id == TaskRecord.task_id)

    count_stmt = (
        sa.select(sa.func.count())
        .select_from(join_from)
        .where(*filters)
    )
    stmt = (
        sa.select(LogRecord)
        .join(TaskRecord, LogRecord.task_id == TaskRecord.task_id)
        .where(*filters)
        .order_by(sa.desc(LogRecord.created_at), sa.desc(LogRecord.id))
        .limit(limit)
        .offset(offset)
    )

    total = int((await session.execute(count_stmt)).scalar_one())
    items = list((await session.execute(stmt)).scalars().all())

    return LogEntriesPageSchema(
        items=[LogEntrySchema.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
        has_more=build_has_more(offset=offset, page_size=len(items), total=total),
    )
