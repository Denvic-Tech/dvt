from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from core.dump_engine import dump, load

from src.modules.pipeline_cache.domain.entities import DataIndexEntry
from src.modules.pipeline_cache.domain.keys import JSONKey, PDFKey
from src.modules.pipeline_cache.domain.value_objects import RedisStoreSettings
from src.modules.pipeline_cache.infra.repositories import RedisBlobStore, RedisIndexStore

pytestmark = [pytest.mark.asyncio, pytest.mark.docker_required]


def _redis_url(redis_container) -> str:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"


def _blob_store(redis_container) -> RedisBlobStore:
    return RedisBlobStore(
        RedisStoreSettings(
            redis_url=_redis_url(redis_container),
            key_prefix=f"pipeline-cache/blob/{uuid4().hex}",
            default_ttl=600,
            idle_connection_ttl_sec=180,
            idle_sweep_interval_sec=30,
        )
    )


def _index_store(redis_container) -> RedisIndexStore:
    return RedisIndexStore(
        serializer=dump,
        deserializer=load,
        settings=RedisStoreSettings(
            redis_url=_redis_url(redis_container),
            key_prefix=f"pipeline-cache/index/{uuid4().hex}",
            default_ttl=600,
            idle_connection_ttl_sec=180,
            idle_sweep_interval_sec=30,
            separator=":::",
        ),
    )


async def test_redis_blob_store_roundtrip(redis_container) -> None:
    store = _blob_store(redis_container)
    try:
        await store.put("cache-key", b"payload")
        await store.put("df:project:node:g:part:0", b"one")
        await store.put("df:project:node:g:part:1", b"two")
        assert await store.has("cache-key") is True
        assert await store.get("cache-key") == b"payload"
        assert await store.has_many(
            ["df:project:node:g:part:0", "df:project:node:g:part:1"]
        ) is True
        assert await store.has_many(
            ["df:project:node:g:part:0", "df:project:node:g:part:missing"]
        ) is False
        assert await store.keys("df:project:node:") == [
            "df:project:node:g:part:0",
            "df:project:node:g:part:1",
        ]
        await store.remove("cache-key")
        assert await store.has("cache-key") is False
    finally:
        await store.clear()
        await store.close()


async def test_redis_blob_store_compare_and_set_is_atomic(redis_container) -> None:
    store = _blob_store(redis_container)
    try:
        assert await store.compare_and_set(
            "active", expected=None, payload=b"initial", ttl=600
        )

        async def swap(expected: bytes, payload: bytes) -> bool:
            return await store.compare_and_set(
                "active", expected=expected, payload=payload, ttl=600
            )

        first, second = await asyncio.gather(
            swap(b"initial", b"new-a"),
            swap(b"initial", b"new-b"),
        )
        assert sum((first, second)) == 1
        assert await store.get("active") in {b"new-a", b"new-b"}
    finally:
        await store.clear()
        await store.close()


async def test_redis_index_store_supports_partial_queries(redis_container) -> None:
    store = _index_store(redis_container)
    base_key = PDFKey(project_id="proj-1", node_id="node-1", output_name=None, part_no=None)
    key_one = PDFKey(project_id="proj-1", node_id="node-1", output_name="out", part_no=1)
    key_two = PDFKey(project_id="proj-1", node_id="node-1", output_name="out", part_no=2)

    try:
        await store.put(key_one, DataIndexEntry(cache_key="cache-1", output_name="out"))
        await store.put(key_two, DataIndexEntry(cache_key="cache-2", output_name="out"))

        assert await store.contains(base_key) is True
        queried = await store.query(base_key)
        assert sorted(entry.cache_key for entry in queried) == ["cache-1", "cache-2"]

        json_key = JSONKey(project_id="proj-2", node_id="node-2", output_name="json")
        await store.put(json_key, DataIndexEntry(cache_key="cache-json", output_name="json"))
        keys = await store.keys(JSONKey)
        assert keys == [json_key]
    finally:
        await store.clear()
        await store.close()
