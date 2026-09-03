import orjson
import pytest

from core.storage import in_memory_bytes as storage_module
from core.storage.in_memory_bytes import InMemoryBytesStorage


class _FakeEngine:
    def __init__(self, name: str = "fake") -> None:
        self.name = name
        self.dump_calls = []
        self.load_calls = []

    def dump(self, value):
        self.dump_calls.append(value)
        return b"payload", {"meta": "ok"}

    def load(self, data, meta=None):
        self.load_calls.append((data, meta))
        return f"loaded:{data!s}"


@pytest.mark.asyncio
async def test_put_serializes_with_engine(monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(storage_module, "pick_engine_for", lambda value: engine)

    storage = InMemoryBytesStorage()
    await storage.put("alpha", {"x": 1})

    payload = orjson.loads(storage._cache["alpha"])
    assert payload["cache_engine"] == "fake"
    assert payload["data_hex"] == b"payload".hex()
    assert payload["meta"] == {"meta": "ok"}
    assert engine.dump_calls == [{"x": 1}]


@pytest.mark.asyncio
async def test_get_deserializes_with_engine(monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(storage_module, "get_engine_by_name", lambda name: engine)

    storage = InMemoryBytesStorage()

    payload = {
        "cache_engine": "fake",
        "data_hex": b"data".hex(),
        "meta": {"meta": "ok"},
    }
    storage._cache["alpha"] = orjson.dumps(payload)

    result = await storage.get("alpha")

    assert result == "loaded:b'data'"
    assert engine.load_calls == [(b"data", {"meta": "ok"})]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"cache_engine": "fake"},
        {"data_hex": b"data".hex()},
    ],
)
async def test_get_with_invalid_payload_raises_value_error(payload):
    storage = InMemoryBytesStorage()
    storage._cache["broken"] = orjson.dumps(payload)

    with pytest.raises(ValueError):
        await storage.get("broken")


@pytest.mark.asyncio
async def test_get_with_unknown_engine_raises_key_error(monkeypatch):
    monkeypatch.setattr(storage_module, "get_engine_by_name", lambda name: None)

    storage = InMemoryBytesStorage()
    payload = {
        "cache_engine": "missing",
        "data_hex": b"data".hex(),
        "meta": {},
    }
    storage._cache["broken"] = orjson.dumps(payload)

    with pytest.raises(KeyError):
        await storage.get("broken")


@pytest.mark.asyncio
async def test_remove_and_clear_trigger_callback(monkeypatch):
    removed = []
    engine = _FakeEngine()
    monkeypatch.setattr(storage_module, "pick_engine_for", lambda value: engine)
    storage = InMemoryBytesStorage(on_item_remove=removed.append)

    await storage.put("first", 1)
    await storage.put("second", 2)

    await storage.remove("first", "missing", "second")

    assert removed == ["first", "second"]

    await storage.put("first", 1)
    await storage.put("second", 2)

    await storage.clear()

    assert set(removed) == {"first", "second"}
    assert await storage.keys() == []


@pytest.mark.asyncio
async def test_keys_values_items_dict_return_raw_bytes(monkeypatch):
    engine = _FakeEngine()
    monkeypatch.setattr(storage_module, "pick_engine_for", lambda value: engine)

    storage = InMemoryBytesStorage()

    await storage.put("first", 1)
    await storage.put("second", 2)

    values = await storage.values()
    items = await storage.items()
    data = await storage.dict()

    assert all(isinstance(val, (bytes, bytearray)) for val in values)
    assert set(key for key, _ in items) == {"first", "second"}
    assert set(data.keys()) == {"first", "second"}
