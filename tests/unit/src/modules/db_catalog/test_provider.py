import asyncio

import pytest

from src.modules.db_catalog.domain import (
    AuthorizedCatalogConnection,
    CatalogActor,
    CatalogDatabase,
    CatalogOperation,
    CatalogRequest,
    CatalogResult,
)
from src.modules.db_catalog.flow import CatalogProvider


class FakeAccess:
    def __init__(self, events):
        self.events = events

    async def get_authorized(self, connection_id, actor):
        self.events.append("authorize")
        return AuthorizedCatalogConnection(
            id=connection_id,
            revision="revision-1",
            dialect="postgresql",
            configured_database="analytics",
            connection_url="postgresql://user:secret@db/analytics",
        )


class FakeSource:
    def __init__(self, events):
        self.events = events
        self.calls = 0

    async def fetch(self, connection, request):
        self.events.append("source")
        self.calls += 1
        await asyncio.sleep(0)
        return CatalogResult(items=(CatalogDatabase("analytics", True),))


class FakeCache:
    def __init__(self, events):
        self.events = events
        self.entry = None
        self.epoch = 0
        self.locked = False
        self.ready = asyncio.Event()

    async def get_epoch(self, connection_id, revision):
        self.events.append("epoch")
        return self.epoch

    async def increment_epoch(self, connection_id, revision):
        self.epoch += 1
        return self.epoch

    async def get(self, key):
        self.events.append("cache_get")
        return self.entry

    async def set(self, key, entry, ttl_seconds):
        self.entry = entry
        self.ready.set()

    async def try_acquire(self, key, ttl_seconds):
        if self.locked:
            return None
        self.locked = True
        return "token"

    async def release(self, key, token):
        self.locked = False

    async def wait_for_entry(self, key, timeout_seconds):
        await asyncio.wait_for(self.ready.wait(), timeout_seconds)
        return self.entry


def _provider():
    events = []
    source = FakeSource(events)
    cache = FakeCache(events)
    return CatalogProvider(
        connection_access=FakeAccess(events),
        source=source,
        cache=cache,
        cache_ttl_seconds=60,
        lock_ttl_seconds=35,
    ), source, cache, events


@pytest.mark.asyncio
async def test_provider_authorizes_before_cache_and_reuses_cached_result():
    provider, source, _cache, events = _provider()
    actor = CatalogActor("user", "org", "user")
    request = CatalogRequest(operation=CatalogOperation.DATABASES)

    first = await provider.execute(connection_id="conn", actor=actor, request=request)
    second = await provider.execute(connection_id="conn", actor=actor, request=request)

    assert events[0] == "authorize"
    assert source.calls == 1
    assert first.cache_status.value == "miss"
    assert second.cache_status.value == "hit"


@pytest.mark.asyncio
async def test_provider_singleflight_coalesces_concurrent_misses():
    provider, source, _cache, _events = _provider()
    actor = CatalogActor("user", "org", "user")
    request = CatalogRequest(operation=CatalogOperation.DATABASES)

    responses = await asyncio.gather(*(
        provider.execute(connection_id="conn", actor=actor, request=request)
        for _ in range(5)
    ))

    assert source.calls == 1
    assert {response.result.items[0].name for response in responses} == {"analytics"}


@pytest.mark.asyncio
async def test_refresh_only_authorizes_and_increments_epoch():
    provider, source, cache, _events = _provider()
    result = await provider.refresh(
        connection_id="conn",
        actor=CatalogActor("user", "org", "user"),
    )

    assert source.calls == 0
    assert cache.epoch == 1
    assert result.catalog_version == "revision-1:1"


@pytest.mark.asyncio
async def test_bypass_cache_reads_source_and_replaces_cached_entry():
    provider, source, cache, _events = _provider()
    actor = CatalogActor("user", "org", "user")
    request = CatalogRequest(operation=CatalogOperation.TABLE, table_name="orders")

    warm = await provider.execute(connection_id="conn", actor=actor, request=request)
    bypass = await provider.execute(
        connection_id="conn", actor=actor, request=request, bypass_cache=True
    )
    after = await provider.execute(connection_id="conn", actor=actor, request=request)

    assert source.calls == 2, "обход кэша идёт в источник даже при тёплом кэше"
    assert warm.cache_status.value == "miss"
    assert bypass.cache_status.value == "bypass"
    assert after.cache_status.value == "hit"
    assert cache.entry.loaded_at == bypass.loaded_at, "свежая запись заменила кэш под тем же ключом"
    assert cache.locked is False


@pytest.mark.asyncio
async def test_bypass_cache_does_not_wait_for_or_release_foreign_lock():
    provider, source, cache, _events = _provider()
    cache.locked = True  # lock держит другой запрос

    response = await provider.execute(
        connection_id="conn",
        actor=CatalogActor("user", "org", "user"),
        request=CatalogRequest(operation=CatalogOperation.DATABASES),
        bypass_cache=True,
    )

    assert response.cache_status.value == "bypass"
    assert source.calls == 1
    assert cache.locked is True, "чужой lock не освобождается"
