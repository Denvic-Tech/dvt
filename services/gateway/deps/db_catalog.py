from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

from services.gateway.deps.db_connection import get_connection_service
from services.gateway.deps.redis import get_redis_bytes

from src.modules.db_catalog import CatalogActor, build_catalog_use_cases
from src.modules.user.infra.db_models import UserRecord

import config

RedisBytes = Annotated[Redis, Depends(get_redis_bytes)]


def build_catalog_actor(user: UserRecord) -> CatalogActor:
    return CatalogActor(
        id=user.id,
        organization_id=user.organization_id,
        role=str(user.role),
    )


def get_catalog_use_cases(redis: Redis):
    return build_catalog_use_cases(
        connection_service=get_connection_service(),
        redis=redis,
        cache_ttl_seconds=config.DB_CATALOG.CACHE_TTL_SEC,
        connect_timeout_seconds=config.DB_CATALOG.CONNECT_TIMEOUT_SEC,
        query_timeout_seconds=config.DB_CATALOG.QUERY_TIMEOUT_SEC,
        request_timeout_seconds=config.DB_CATALOG.REQUEST_TIMEOUT_SEC,
        lock_ttl_seconds=config.DB_CATALOG.SINGLEFLIGHT_LOCK_TTL_SEC,
        max_concurrency=config.DB_CATALOG.MAX_CONCURRENCY,
        preview_cell_max_chars=config.DB_CATALOG.PREVIEW_CELL_MAX_CHARS,
        preview_max_response_bytes=config.DB_CATALOG.PREVIEW_MAX_RESPONSE_BYTES,
    )
