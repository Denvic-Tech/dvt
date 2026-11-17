from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.project.infra.db_models import ProjectFavoriteRecord


async def get_favorite_project_ids(
    session: AsyncSession,
    *,
    user_id: str,
    project_ids: Sequence[str],
) -> set[str]:
    """Вернуть подмножество `project_ids`, отмеченных пользователем как избранные."""
    normalized_ids = tuple(dict.fromkeys(project_id for project_id in project_ids if project_id))
    if not normalized_ids:
        return set()

    rows = await session.execute(
        sa.select(ProjectFavoriteRecord.project_id).where(
            ProjectFavoriteRecord.user_id == user_id,
            ProjectFavoriteRecord.project_id.in_(normalized_ids),
        )
    )
    return set(rows.scalars().all())
