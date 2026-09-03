from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.crud import project as project_crud
from src.crud.admin.user.read import get_users_by
from src.models import (
    AIAnalysisRequestRecord,
    LogRecord,
    UsersTokenRecord,
)
from src.modules.db_connection.infra.db_models import DVTStoredConnectionRecord
from src.modules.project.infra.db_models import (
    ProjectFolderRecord,
    ProjectRecord,
    ProjectScheduleRecord,
)
from src.modules.task_execution.infra.db_models import TaskRecord
from src.modules.user.infra.db_models import UserRecord


async def delete_users(
    session: AsyncSession,
    users: Sequence[UserRecord],
    *,
    soft_delete: bool = True,
) -> Sequence[UserRecord]:
    if soft_delete:
        user_ids = [user.id for user in users if user.id is not None]
        if not user_ids:
            return users

        stmt = (
            sa.update(UserRecord)
            .where(UserRecord.id.in_(user_ids))
            .values(is_active=False)
            .execution_options(synchronize_session="fetch")
        )
        await session.execute(stmt)
        await session.flush()
        for user in users:
            await session.refresh(user)
        return users

    user_ids = tuple(user.id for user in users if user.id is not None)
    project_ids = list(
        (
            await session.execute(
                sa.select(ProjectRecord.id).where(ProjectRecord.user_id.in_(user_ids))
            )
        ).scalars()
    )
    await project_crud.delete_projects_permanently(session, project_ids=project_ids)

    user_task_ids = sa.select(TaskRecord.task_id).where(TaskRecord.user_id.in_(user_ids))
    await session.execute(
        sa.update(LogRecord).where(LogRecord.task_id.in_(user_task_ids)).values(task_id=None)
    )
    await session.execute(
        sa.update(LogRecord).where(LogRecord.user_id.in_(user_ids)).values(user_id=None)
    )
    await session.execute(
        sa.delete(AIAnalysisRequestRecord).where(AIAnalysisRequestRecord.user_id.in_(user_ids))
    )
    await session.execute(sa.delete(TaskRecord).where(TaskRecord.user_id.in_(user_ids)))
    await session.execute(
        sa.update(ProjectScheduleRecord)
        .where(ProjectScheduleRecord.scheduled_by_user_id.in_(user_ids))
        .values(scheduled_by_user_id=None)
    )

    folder_ids = sa.select(ProjectFolderRecord.id).where(ProjectFolderRecord.user_id.in_(user_ids))
    await session.execute(
        sa.update(ProjectFolderRecord)
        .where(ProjectFolderRecord.parent_id.in_(folder_ids))
        .values(parent_id=None)
    )
    await session.execute(
        sa.delete(ProjectFolderRecord).where(ProjectFolderRecord.user_id.in_(user_ids))
    )
    await session.execute(
        sa.delete(DVTStoredConnectionRecord).where(DVTStoredConnectionRecord.user_id.in_(user_ids))
    )
    await session.execute(sa.delete(UsersTokenRecord).where(UsersTokenRecord.user_id.in_(user_ids)))

    for user in users:
        await session.delete(user)
    await session.flush()
    return users


async def delete_users_by(
    session: AsyncSession,
    *,
    user_id: str | None = None,
    email: str | None = None,
    user_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
    is_verified: bool | None = None,
    organization_id: str | None = None,
    email_contains: str | None = None,
    soft_delete: bool = True,
) -> list[str]:
    users = list(
        (
            await get_users_by(
                session,
                user_id=user_id,
                email=email,
                user_name=user_name,
                role=role,
                is_active=is_active,
                is_verified=is_verified,
                organization_id=organization_id,
                email_contains=email_contains,
            )
        ).all()
    )

    if not users:
        return []

    deleted_users = await delete_users(session, users, soft_delete=soft_delete)
    return [user.id for user in deleted_users if user.id is not None]
