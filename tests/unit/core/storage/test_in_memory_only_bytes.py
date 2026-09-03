import pytest

from core.storage.in_memory_only_bytes import InMemoryBytesStorage


@pytest.mark.asyncio
async def test_put_requires_bytes_like():
    storage = InMemoryBytesStorage()

    with pytest.raises(TypeError):
        await storage.put("bad", "text")

    await storage.put("bytearray", bytearray(b"abc"))
    await storage.put("memoryview", memoryview(b"def"))

    assert await storage.get("bytearray") == b"abc"
    assert await storage.get("memoryview") == b"def"


@pytest.mark.asyncio
async def test_put_get_has_remove_roundtrip():
    storage = InMemoryBytesStorage()

    await storage.put("alpha", b"data")

    assert await storage.has("alpha") is True
    assert await storage.get("alpha") == b"data"

    await storage.remove("alpha", "missing")

    assert await storage.has("alpha") is False


@pytest.mark.asyncio
async def test_clear_calls_on_item_remove_for_all_keys():
    removed = []
    storage = InMemoryBytesStorage(on_item_remove=removed.append)

    await storage.put("one", b"1")
    await storage.put("two", b"2")

    await storage.clear()

    assert set(removed) == {"one", "two"}
    assert await storage.keys() == []


@pytest.mark.asyncio
async def test_keys_values_items_dict_return_collections():
    storage = InMemoryBytesStorage()

    await storage.put("first", b"a")
    await storage.put("second", b"b")

    assert set(await storage.keys()) == {"first", "second"}
    assert set(await storage.values()) == {b"a", b"b"}
    assert set(await storage.items()) == {("first", b"a"), ("second", b"b")}
    assert await storage.dict() == {"first": b"a", "second": b"b"}
