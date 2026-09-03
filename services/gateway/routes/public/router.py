from fastapi import APIRouter

from src.db import async_engine
from src.modules.db_connection import build_db_connection_extension
from src.modules.user.infra.fastapi.dependencies import get_user_any_auth
from src.modules.user.infra.repositories import SQLAlchemyUserRepository

import config

from .admin.router import router as admin_router
from .organization.router import router as organization_router
from .project.task import router as project_task_router

router = APIRouter(prefix="/public")

router.include_router(project_task_router, prefix="/projects/{project_id}", tags=["Project Tasks"])
router.include_router(organization_router)
router.include_router(admin_router)


public_db_connections_ext = build_db_connection_extension(
    engine=async_engine,
    fernet_key=config.SECURITY.FERNET_KEY,
    get_actor_dependency=get_user_any_auth,
    user_repository_factory=SQLAlchemyUserRepository,
)
public_db_connections_ext.install(router, prefix="/db-connections", tags=["DB Connections"])
