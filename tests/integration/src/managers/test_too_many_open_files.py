from __future__ import annotations

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from core.dump_engine import dump, load
from src.modules.pipeline_cache import PDFKey, RedisBlobStore, RedisIndexStore, RedisStoreSettings

pytestmark = pytest.mark.asyncio


def _emfile_error() -> RedisConnectionError:
    return RedisConnectionError("Error 24 connecting to valkey:6379. Too many open files.")


async def _raise_emfile(*_args, **_kwargs):
    raise _emfile_error()


def _settings(key_prefix: str) -> RedisStoreSettings:
    return RedisStoreSettings(
        redis_url="redis://127.0.0.1:6379/0",
        key_prefix=key_prefix,
        default_ttl=600,
        idle_connection_ttl_sec=180,
        idle_sweep_interval_sec=30,
        separator=":::",
    )


async def test_redis_blob_store_emfile_is_propagated(monkeypatch) -> None:
    store = RedisBlobStore(_settings("tests/emfile/blob"))
    monkeypatch.setattr(store._clients, "get_client", _raise_emfile)

    with pytest.raises(RedisConnectionError, match=r"Error 24.*Too many open files"):
        await store.get("sample-key")


async def test_redis_index_store_emfile_is_propagated(monkeypatch) -> None:
    store = RedisIndexStore(
        serializer=dump,
        deserializer=load,
        settings=_settings("tests/emfile/index"),
    )
    monkeypatch.setattr(store._clients, "get_client", _raise_emfile)

    index_key = PDFKey(
        project_id="proj",
        node_id="node",
        output_name="out",
        part_no=0,
    )
    with pytest.raises(RedisConnectionError, match=r"Error 24.*Too many open files"):
        await store.contains(index_key)
