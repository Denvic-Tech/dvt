from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from src.crud import project as project_crud
from src.db import AsyncSession
from src.modules.project.infra.db_models import ProjectFavoriteRecord, ProjectRecord
from src.modules.user.infra.db_models import UserRecord
from src.schemas.http.common import CommonResponse
from src.schemas.http.project import ProjectReadSchema
from src.utils.access_control import build_owner_or_org_filters

from .crud import _get_last_runs_by_project_id, _project_to_read_schema


async def get_favorite_projects_route_impl(
        *,
        session: AsyncSession,
        user: UserRecord,
) -> list[ProjectReadSchema]:
    stmt = (
        sa.select(ProjectRecord)
        .join(
            ProjectFavoriteRecord,
            ProjectFavoriteRecord.project_id == ProjectRecord.id,
        )
        .where(
            ProjectFavoriteRecord.user_id == user.id,
            ProjectRecord.is_deleted.is_(False),
            *build_owner_or_org_filters(
                user=user,
                organization_column=ProjectRecord.organization_id,
                owner_column=ProjectRecord.user_id,
            ),
        )
        .order_by(ProjectFavoriteRecord.created_at.desc(), ProjectRecord.id)
    )
    projects = (await session.execute(stmt)).scalars().all()
    if not projects:
        return []

    user_emails = await project_crud.get_user_emails_by_ids(
        session,
        user_ids=[project.user_id for project in projects],
    )
    last_runs_by_project_id = await _get_last_runs_by_project_id(
        session=session,
        user=user,
        project_ids=[project.id for project in projects],
    )
    return [
        _project_to_read_schema(
            project,
            user_email=user_emails.get(project.user_id),
            last_runs_by_project_id=last_runs_by_project_id,
            is_favorite=True,
        )
        for project in projects
    ]


async def add_favorite_project_route_impl(
        *,
        session: AsyncSession,
        user: UserRecord,
        project: ProjectRecord,
) -> CommonResponse:
    """Идемпотентно добавить проект в избранное текущего пользователя."""
    existing = await project_crud.get_favorite_project_ids(
        session,
        user_id=user.id,
        project_ids=[project.id],
    )
    if project.id in existing:
        return CommonResponse(success=True, message="Project is already in favorites.")

    session.add(
        ProjectFavoriteRecord(
            user_id=user.id,
            project_id=project.id,
            created_at=datetime.now(tz=UTC),
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        # Параллельный запрос успел добавить ту же запись; результат тот же.
        await session.rollback()

    return CommonResponse(success=True, message="Project added to favorites.")


async def remove_favorite_project_route_impl(
        *,
        session: AsyncSession,
        user: UserRecord,
        project: ProjectRecord,
) -> CommonResponse:
    """Идемпотентно убрать проект из избранного текущего пользователя."""
    await session.execute(
        sa.delete(ProjectFavoriteRecord).where(
            ProjectFavoriteRecord.user_id == user.id,
            ProjectFavoriteRecord.project_id == project.id,
        )
    )
    await session.commit()
    return CommonResponse(success=True, message="Project removed from favorites.")
