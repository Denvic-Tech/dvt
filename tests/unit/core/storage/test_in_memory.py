import asyncio

import pytest

from core.storage.in_memory import InMemoryStorage


@pytest.mark.asyncio
async def test_put_get_has_roundtrip():
    storage = InMemoryStorage()

    await storage.put("alpha", 123)

    assert await storage.has("alpha") is True
    assert await storage.get("alpha") == 123
    assert await storage.has("missing") is False


@pytest.mark.asyncio
async def test_remove_calls_on_item_remove_for_existing_keys():
    removed = []
    storage = InMemoryStorage(on_item_remove=removed.append)

    await storage.put("one", "a")
    await storage.put("two", "b")

    await storage.remove("one", "missing", "two")

    assert removed == ["one", "two"]
    assert await storage.has("one") is False
    assert await storage.has("two") is False


@pytest.mark.asyncio
async def test_clear_calls_on_item_remove_for_all_keys():
    removed = []
    storage = InMemoryStorage(on_item_remove=removed.append)

    await storage.put("one", 1)
    await storage.put("two", 2)

    await storage.clear()

    assert set(removed) == {"one", "two"}
    assert await storage.keys() == []


@pytest.mark.asyncio
async def test_keys_values_items_dict_return_collections():
    storage = InMemoryStorage()

    await storage.put("first", "a")
    await storage.put("second", "b")

    assert set(await storage.keys()) == {"first", "second"}
    assert set(await storage.values()) == {"a", "b"}
    assert set(await storage.items()) == {("first", "a"), ("second", "b")}
    assert await storage.dict() == {"first": "a", "second": "b"}


@pytest.mark.asyncio
async def test_get_does_not_block_on_write_lock():
    storage = InMemoryStorage()

    await storage.put("alpha", 123)

    async with storage._write_lock:
        get_task = asyncio.create_task(storage.get("alpha"))
        await asyncio.sleep(0)
        assert get_task.done() is True
        assert await get_task == 123

        put_task = asyncio.create_task(storage.put("beta", 456))
        await asyncio.sleep(0)
        assert put_task.done() is False

    await put_task
    assert await storage.get("beta") == 456
