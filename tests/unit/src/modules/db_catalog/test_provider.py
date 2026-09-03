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
