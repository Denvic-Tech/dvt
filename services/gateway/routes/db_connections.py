from src.db import async_engine
from src.modules.db_connection import build_db_connection_extension
from src.modules.user.infra.fastapi.dependencies import get_user_access_only
from src.modules.user.infra.repositories import SQLAlchemyUserRepository

import config

from .impl.db_catalog import router as db_catalog_router

main_db_connections_ext = build_db_connection_extension(
    engine=async_engine,
    fernet_key=config.SECURITY.FERNET_KEY,
    get_actor_dependency=get_user_access_only,
    user_repository_factory=SQLAlchemyUserRepository
)
router = main_db_connections_ext.build_router(prefix="/db-connections", tags=["DB Connections"])
router.include_router(db_catalog_router)
