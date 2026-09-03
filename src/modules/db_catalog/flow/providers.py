from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ..domain.entities import (
    CatalogActor,
    CatalogCacheEntry,
    CatalogRefreshResult,
    CatalogResponse,
)
from ..domain.gateways import CatalogCacheGateway, CatalogSourceGateway, ConnectionAccessGateway
from ..domain.policies import build_cache_key, validate_request
from ..domain.types import CatalogCacheStatus
from ..domain.value_objects import CatalogRequest


class CatalogProvider:
    def __init__(
        self,
        *,
        connection_access: ConnectionAccessGateway,
        source: CatalogSourceGateway,
        cache: CatalogCacheGateway,
        cache_ttl_seconds: int,
        lock_ttl_seconds: int,
    ) -> None:
        self._connection_access = connection_access
        self._source = source
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds
        self._lock_ttl_seconds = lock_ttl_seconds

    async def execute(
        self,
        *,
        connection_id: str,
        actor: CatalogActor,
        request: CatalogRequest,
    ) -> CatalogResponse:
        connection = await self._connection_access.get_authorized(connection_id, actor)
        validate_request(connection, request)
        epoch = await self._cache.get_epoch(connection.id, connection.revision)
        key = build_cache_key(connection, request, epoch)
        cached = await self._cache.get(key)
        if cached is not None:
            return self._response(cached, CatalogCacheStatus.HIT, connection.dialect)

        token = await self._cache.try_acquire(key, self._lock_ttl_seconds)
        if token is None:
            cached = await self._cache.wait_for_entry(key, self._lock_ttl_seconds)
            if cached is not None:
                return self._response(cached, CatalogCacheStatus.HIT, connection.dialect)
            token = await self._cache.try_acquire(key, self._lock_ttl_seconds)

        try:
            result = await self._source.fetch(connection, request)
            loaded_at = datetime.now(UTC)
            entry = CatalogCacheEntry(
                result=result,
                catalog_version=f"{connection.revision}:{epoch}",
                loaded_at=loaded_at,
                expires_at=loaded_at + timedelta(seconds=self._cache_ttl_seconds),
            )
            await self._cache.set(key, entry, self._cache_ttl_seconds)
            return self._response(entry, CatalogCacheStatus.MISS, connection.dialect)
        finally:
            if token is not None:
                await self._cache.release(key, token)

    async def refresh(
        self,
        *,
        connection_id: str,
        actor: CatalogActor,
    ) -> CatalogRefreshResult:
        connection = await self._connection_access.get_authorized(connection_id, actor)
        epoch = await self._cache.increment_epoch(connection.id, connection.revision)
        return CatalogRefreshResult(catalog_version=f"{connection.revision}:{epoch}")

    @staticmethod
    def _response(
        entry: CatalogCacheEntry,
        status: CatalogCacheStatus,
        dialect: str,
    ) -> CatalogResponse:
        return CatalogResponse(
            result=entry.result,
            dialect=dialect,
            catalog_version=entry.catalog_version,
            loaded_at=entry.loaded_at,
            expires_at=entry.expires_at,
            cache_status=status,
        )
