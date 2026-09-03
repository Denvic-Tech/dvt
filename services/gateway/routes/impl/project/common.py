from src.db import AsyncSession
from src.exceptions import TaskNotFoundException
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.infra.queries import TaskReadModel, get_accessible_task
from src.modules.user.infra.db_models import UserRecord
from src.utils.access_control import get_access_scope

PROJECT_ITEMS_DEFAULT_LIMIT = 50
PROJECT_ITEMS_MAX_LIMIT = 200
PROJECT_LOGS_DEFAULT_LIMIT = 100
PROJECT_LOGS_MAX_LIMIT = 500


async def get_project_task_or_404(
        *,
        session: AsyncSession,
        project: ProjectRecord,
        user: UserRecord,
        task_id: str,
) -> TaskReadModel:
    access_scope = get_access_scope(user)
    task = await get_accessible_task(
        session=session,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        project_id=project.id,
        task_id=task_id,
    )
    if task is None:
        raise TaskNotFoundException(status_code=404, detail=f"Task ID={task_id} not found.")
    return task


def build_has_more(*, offset: int, page_size: int, total: int) -> bool:
    return offset + page_size < total
