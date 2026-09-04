from typing import Optional

from fastapi import Depends, Request
from usrak.core.dependencies.user import get_optional_user_any

from src.logger import logger
from src.modules.user.infra.db_models import UserRecord


async def set_user_log_context(
    user: Optional[UserRecord] = Depends(get_optional_user_any),
    request: Request = None,
):
    project_id: Optional[str] = request.path_params.get("project_id")
    context = {
        "user_id": user.id if user else None,
        "project_id": project_id,
    }
    with logger.contextualize(**context):
        yield
