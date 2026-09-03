from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import config

from src.modules.pipeline_cache import (
    CacheNamespaces,
    CodecObjectStore,
    CommonOutputKey,
    DataIndexEntry,
    DumpEngineCodec,
    IndexStore,
    MetaKey,
    MetadataCacheEntry,
    ObjectStore,
    PipelineCacheFacade,
    PipelineCacheProvider,
    PipelineCacheSettings,
    RedisBlobStore,
    RedisIndexStore,
    RedisStoreSettings,
)


@dataclass(frozen=True)
class PipelineCacheRuntime:
    facade: PipelineCacheFacade
    data_store: ObjectStore[Any]
    data_index_store: IndexStore[CommonOutputKey, DataIndexEntry]
    metadata_store: ObjectStore[MetadataCacheEntry]
    metadata_index_store: IndexStore[MetaKey, str]


def _build_redis_url() -> str:
    auth = f":{config.VALKEY.VALKEY_PASSWORD}@" if config.VALKEY.VALKEY_PASSWORD else ""
    return f"redis://{auth}{config.VALKEY.VALKEY_HOST}:{config.VALKEY.VALKEY_PORT}/{config.VALKEY.VALKEY_DB}"


def _build_cache_settings() -> PipelineCacheSettings:
    return PipelineCacheSettings(
        namespaces=CacheNamespaces(
            data="pipeline_cache/data",
            data_index="pipeline_cache/data_index",
            metadata="pipeline_cache/metadata",
            metadata_index="pipeline_cache/metadata_index",
        ),
        default_ttl=config.OTHER.DEFAULT_CACHE_TTL,
        index_separator=":::",
    )


def _build_redis_store_settings(key_prefix: str, *, separator: str) -> RedisStoreSettings:
    return RedisStoreSettings(
        redis_url=_build_redis_url(),
        key_prefix=key_prefix,
        default_ttl=config.OTHER.DEFAULT_CACHE_TTL,
        idle_connection_ttl_sec=config.OTHER.REDIS_IDLE_CONNECTION_TTL_SEC,
        idle_sweep_interval_sec=config.OTHER.REDIS_IDLE_SWEEP_INTERVAL_SEC,
        separator=separator,
    )


@lru_cache(maxsize=1)
def get_pipeline_cache_runtime() -> PipelineCacheRuntime:
    settings = _build_cache_settings()
    data_codec = DumpEngineCodec()
    metadata_codec = DumpEngineCodec(dump_kwargs={"mode": "meta"})

    data_blob_store = RedisBlobStore(
        _build_redis_store_settings(settings.namespaces.data, separator=settings.index_separator)
    )
    metadata_blob_store = RedisBlobStore(
        _build_redis_store_settings(settings.namespaces.metadata, separator=settings.index_separator)
    )
    data_index_store = RedisIndexStore(
        serializer=data_codec.dump,
        deserializer=data_codec.load,
        settings=_build_redis_store_settings(settings.namespaces.data_index, separator=settings.index_separator),
    )
    metadata_index_store = RedisIndexStore(
        serializer=lambda cache_key: cache_key.encode("utf-8"),
        deserializer=lambda payload: payload.decode("utf-8"),
        settings=_build_redis_store_settings(settings.namespaces.metadata_index, separator=settings.index_separator),
    )
    data_store = CodecObjectStore(data_blob_store, data_codec)
    metadata_store = CodecObjectStore(metadata_blob_store, metadata_codec)
    provider = PipelineCacheProvider(
        settings=settings,
        data_blob_store=data_blob_store,
        data_index_store=data_index_store,
        metadata_blob_store=metadata_blob_store,
        metadata_index_store=metadata_index_store,
        data_codec=data_codec,
        metadata_codec=metadata_codec,
    )
    return PipelineCacheRuntime(
        facade=provider.create_facade(),
        data_store=data_store,
        data_index_store=data_index_store,
        metadata_store=metadata_store,
        metadata_index_store=metadata_index_store,
    )


def get_pipeline_cache_facade() -> PipelineCacheFacade:
    return get_pipeline_cache_runtime().facade


def get_data_store() -> ObjectStore[Any]:
    return get_pipeline_cache_runtime().data_store


def get_data_index_store() -> IndexStore[CommonOutputKey, DataIndexEntry]:
    return get_pipeline_cache_runtime().data_index_store


def get_metadata_store() -> ObjectStore[MetadataCacheEntry]:
    return get_pipeline_cache_runtime().metadata_store


def get_metadata_index_store() -> IndexStore[MetaKey, str]:
    return get_pipeline_cache_runtime().metadata_index_store
