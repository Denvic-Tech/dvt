from functools import lru_cache
from typing import Annotated

from fastapi import Body, Path, Query

from src.db import async_engine
from src.modules.db_connection import ConnectionRecord, build_connection_service
from src.modules.user.infra.db_models import UserRecord
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.modules.user.infra.repositories import SQLAlchemyUserRepository

import config

DBConnectionIDFromPath = Annotated[str, Path(..., description="DBConnectionID")]
DBConnectionIDFromBody = Annotated[str, Body(..., description="DBConnectionID")]
DBConnectionIDFromQuery = Annotated[str, Query(..., description="DBConnectionID")]


@lru_cache
def get_connection_service():
    return build_connection_service(
        engine=async_engine,
        fernet_key=config.SECURITY.FERNET_KEY,
        user_repository_factory=SQLAlchemyUserRepository
    )


async def _get_db_connection(
        connection_id: str,
        user: UserRecord,
) -> ConnectionRecord:
    return await get_connection_service().get(connection_id, actor=user)


async def get_user_db_connection_by_path(
        connection_id: DBConnectionIDFromPath,
        user: UserAccessOnly,
) -> ConnectionRecord:
    """
    Dependency для получения DBConnection по Path
    """
    return await _get_db_connection(connection_id=connection_id, user=user)


async def get_user_db_connection_by_body(
        connection_id: DBConnectionIDFromBody,
        user: UserAccessOnly,
) -> ConnectionRecord:
    """
    Dependency для получения DBConnection по Body
    """
    return await _get_db_connection(connection_id=connection_id, user=user)


async def get_user_db_connection_by_query(
        connection_id: DBConnectionIDFromQuery,
        user: UserAccessOnly,
) -> ConnectionRecord:
    """
    Dependency для получения DBConnection по Query
    """
    return await _get_db_connection(connection_id=connection_id, user=user)
