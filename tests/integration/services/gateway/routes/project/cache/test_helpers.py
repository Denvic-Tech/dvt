from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.gateway.routes.project.cache.helpers import clear_data_cache
from src.modules.pipeline_cache import (
    CacheNamespaces,
    CodecObjectStore,
    CommonOutputKey,
    DataIndexEntry,
    DumpEngineCodec,
    JSONKey,
    PipelineCacheProvider,
    PipelineCacheSettings,
    RedisBlobStore,
    RedisIndexStore,
    RedisStoreSettings,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.docker_required]


def _build_redis_url(redis_container) -> str:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"


def _build_provider(redis_container) -> PipelineCacheProvider:
    suffix = uuid4().hex
    settings = PipelineCacheSettings(
        namespaces=CacheNamespaces(
            data=f"it-clear-data-cache/data/{suffix}",
            data_index=f"it-clear-data-cache/data_index/{suffix}",
            metadata=f"it-clear-data-cache/metadata/{suffix}",
            metadata_index=f"it-clear-data-cache/metadata_index/{suffix}",
        ),
        default_ttl=600,
        index_separator=":::",
    )
    redis_url = _build_redis_url(redis_container)
    data_codec = DumpEngineCodec()
    metadata_codec = DumpEngineCodec(dump_kwargs={"mode": "meta"})

    def _store_settings(key_prefix: str) -> RedisStoreSettings:
        return RedisStoreSettings(
            redis_url=redis_url,
            key_prefix=key_prefix,
            default_ttl=settings.default_ttl,
            idle_connection_ttl_sec=180,
            idle_sweep_interval_sec=30,
            separator=settings.index_separator,
        )

    return PipelineCacheProvider(
        settings=settings,
        data_blob_store=RedisBlobStore(_store_settings(settings.namespaces.data)),
        data_index_store=RedisIndexStore(
            serializer=data_codec.dump,
            deserializer=data_codec.load,
            settings=_store_settings(settings.namespaces.data_index),
        ),
        metadata_blob_store=RedisBlobStore(_store_settings(settings.namespaces.metadata)),
        metadata_index_store=RedisIndexStore(
            serializer=lambda value: value.encode("utf-8"),
            deserializer=lambda payload: payload.decode("utf-8"),
            settings=_store_settings(settings.namespaces.metadata_index),
        ),
        data_codec=data_codec,
        metadata_codec=metadata_codec,
    )


async def _put_cached_output(
    *,
    facade,
    project_id: str,
    node_id: str,
    output_name: str,
    cache_key: str,
    payload: object,
) -> None:
    await facade.put_data_entry(
        cache_key=cache_key,
        value=payload,
        index_entries=[
            (
                CommonOutputKey(project_id=project_id, node_id=node_id, output_name=output_name),
                DataIndexEntry(cache_key=cache_key, output_name=output_name),
            )
        ],
    )


@pytest.mark.asyncio
async def test_clear_data_cache_clears_selected_nodes(redis_container) -> None:
    project = SimpleNamespace(id="project-1")
    provider = _build_provider(redis_container)
    facade = provider.create_facade()

    try:
        await _put_cached_output(
            facade=facade,
            project_id=project.id,
            node_id="node-1",
            output_name="out-1",
            cache_key="cache-1",
            payload={"value": 1},
        )
        await _put_cached_output(
            facade=facade,
            project_id=project.id,
            node_id="node-1",
            output_name="out-2",
            cache_key="cache-2",
            payload={"value": 2},
        )
        await _put_cached_output(
            facade=facade,
            project_id=project.id,
            node_id="node-2",
            output_name="out-1",
            cache_key="cache-3",
            payload={"value": 3},
        )
        await _put_cached_output(
            facade=facade,
            project_id=project.id,
            node_id="node-3",
            output_name="out-1",
            cache_key="cache-4",
            payload={"value": 4},
        )

        result = await clear_data_cache(
            project=project,
            pipeline_cache=facade,
            node_ids=["node-1", "node-2"],
        )

        assert sorted(result.cleared_keys) == sorted(["cache-1", "cache-2", "cache-3"])
        assert await provider.data_blob_store.has("cache-1") is False
        assert await provider.data_blob_store.has("cache-2") is False
        assert await provider.data_blob_store.has("cache-3") is False
        assert await provider.data_blob_store.has("cache-4") is True
        assert await provider.data_index_store.query(CommonOutputKey(project_id=project.id, node_id="node-1")) == []
        assert await provider.data_index_store.query(CommonOutputKey(project_id=project.id, node_id="node-2")) == []

        remaining_entries = await provider.data_index_store.query(
            CommonOutputKey(project_id=project.id, node_id="node-3")
        )
        assert [entry.cache_key for entry in remaining_entries] == ["cache-4"]
    finally:
        await provider.data_blob_store.clear()
        await provider.data_index_store.clear()
        await provider.data_blob_store.close()
        await provider.data_index_store.close()


@pytest.mark.asyncio
async def test_clear_data_cache_clears_whole_project_when_node_ids_not_provided(redis_container) -> None:
    project = SimpleNamespace(id="project-1")
    provider = _build_provider(redis_container)
    facade = provider.create_facade()

    try:
        await _put_cached_output(
            facade=facade,
            project_id=project.id,
            node_id="node-1",
            output_name="out-1",
            cache_key="cache-1",
            payload={"value": 1},
        )
        await _put_cached_output(
            facade=facade,
            project_id=project.id,
            node_id="node-2",
            output_name="out-1",
            cache_key="cache-2",
            payload={"value": 2},
        )
        await _put_cached_output(
            facade=facade,
            project_id="project-2",
            node_id="node-1",
            output_name="out-1",
            cache_key="cache-3",
            payload={"value": 3},
        )

        result = await clear_data_cache(project=project, pipeline_cache=facade)

        assert sorted(result.cleared_keys) == sorted(["cache-1", "cache-2"])
        assert await provider.data_blob_store.has("cache-1") is False
        assert await provider.data_blob_store.has("cache-2") is False
        assert await provider.data_blob_store.has("cache-3") is True
        assert await provider.data_index_store.query(CommonOutputKey(project_id=project.id)) == []

        remaining_entries = await provider.data_index_store.query(CommonOutputKey(project_id="project-2"))
        assert [entry.cache_key for entry in remaining_entries] == ["cache-3"]
    finally:
        await provider.data_blob_store.clear()
        await provider.data_index_store.clear()
        await provider.data_blob_store.close()
        await provider.data_index_store.close()


@pytest.mark.asyncio
async def test_clear_data_cache_keeps_unrelated_cache_when_index_is_empty(redis_container) -> None:
    project = SimpleNamespace(id="project-1")
    provider = _build_provider(redis_container)
    facade = provider.create_facade()
    data_store = CodecObjectStore(provider.data_blob_store, provider.data_codec)

    try:
        await data_store.put("cache-unrelated", {"value": "keep"})
        await facade.put_data_entry(
            cache_key="cache-foreign",
            value={"value": "keep-indexed"},
            index_entries=[
                (
                    JSONKey(project_id="project-2", node_id="node-2", output_name="json"),
                    DataIndexEntry(cache_key="cache-foreign", output_name="json"),
                )
            ],
        )

        result = await clear_data_cache(project=project, pipeline_cache=facade)

        assert result.cleared_keys == []
        assert await data_store.has("cache-unrelated") is True
        assert await data_store.get("cache-unrelated") == {"value": "keep"}
        assert await provider.data_index_store.query(CommonOutputKey(project_id=project.id)) == []
    finally:
        await provider.data_blob_store.clear()
        await provider.data_index_store.clear()
        await provider.data_blob_store.close()
        await provider.data_index_store.close()
