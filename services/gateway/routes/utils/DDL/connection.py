from dataclasses import dataclass

from db_connection import AccessDeniedError, ConnectionNotFoundError
from fastapi import HTTPException, status
from redis.asyncio import Redis

from services.gateway.deps.db_catalog import build_catalog_actor, get_catalog_use_cases
from services.gateway.deps.db_connection import get_connection_service

from src.modules.user.infra.db_models import UserRecord
from src.node_dsl.connection_types import SqlConnectionRecord
from src.node_dsl.runtime.connections import resolve_sql_connection_url


@dataclass(frozen=True, slots=True)
class ResolvedDDLConnection:
    connection_id: str
    connection_string: str


async def resolve_ddl_connection(
    connection_id: str,
    user: UserRecord,
) -> ResolvedDDLConnection:
    try:
        record = await get_connection_service().get(connection_id, actor=user)
    except (AccessDeniedError, ConnectionNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="DB connection was not found or is not accessible.",
        ) from exc

    try:
        connection = SqlConnectionRecord(record)
    except TypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="DDL operations require a SQL connection.",
        ) from exc

    url = resolve_sql_connection_url(connection)
    return ResolvedDDLConnection(
        connection_id=connection.id,
        connection_string=(
            url
            if isinstance(url, str)
            else url.render_as_string(hide_password=False)
        ),
    )


async def invalidate_ddl_catalog(
    *,
    connection_id: str,
    user: UserRecord,
    redis: Redis,
) -> None:
    await get_catalog_use_cases(redis).refresh.execute(
        connection_id=connection_id,
        actor=build_catalog_actor(user),
    )
