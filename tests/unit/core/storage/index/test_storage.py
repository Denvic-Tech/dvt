import pytest

from core.storage.in_memory import InMemoryStorage
from core.storage.index.base_key import IndexKeyBase
from core.storage.index.storage import IndexStorage, ItemSet


class SampleKey(IndexKeyBase):
    first: str
    second: str | None = None
    third: str | None = None


class Payload:
    def __init__(self, name: str, score: int) -> None:
        self.name = name
        self.score = score

    def __repr__(self) -> str:
        return f"Payload(name={self.name!r}, score={self.score!r})"


def test_itemset_first_and_all_empty():
    items = ItemSet()

    assert items.first() is None
    assert items.all() == []


def test_itemset_first_single_and_order_by_preserves_items():
    payload = Payload("alpha", 2)
    items = ItemSet([payload])

    assert items.first() is payload

    ordered = items.order_by("score", reverse=True)

    assert isinstance(ordered, ItemSet)
    assert set(ordered) == {payload}


@pytest.mark.asyncio
async def test_index_storage_put_and_get_by_store_key_roundtrip():
    store = InMemoryStorage()
    storage = IndexStorage(store, separator=":")
    key = SampleKey(first="group", second="item", third="leaf")

    store_key = await storage.put(key, "value")

    assert store_key == "sample_key\x1Fgroup\x1Fitem\x1Fleaf"
    assert await storage.get_by_store_key(store_key) == "value"
    assert storage.store_key_to_index_key(store_key) == "sample_key:group:item:leaf"


@pytest.mark.asyncio
async def test_index_storage_put_rejects_non_index_key():
    store = InMemoryStorage()
    storage = IndexStorage(store)

    with pytest.raises(TypeError):
        await storage.put("bad", "value")


@pytest.mark.asyncio
async def test_index_storage_put_rejects_empty_segment():
    store = InMemoryStorage()
    storage = IndexStorage(store)
    key = SampleKey(first="", second="a", third="b")

    with pytest.raises(ValueError):
        await storage.put(key, "value")


@pytest.mark.asyncio
async def test_remove_by_prefix_and_contains():
    store = InMemoryStorage()
    storage = IndexStorage(store)

    key_a1 = SampleKey(first="a", second="1", third="x")
    key_a2 = SampleKey(first="a", second="1", third="y")
    key_b = SampleKey(first="a", second="2", third="z")

    key_a1_store = await storage.put(key_a1, "v1")
    key_a2_store = await storage.put(key_a2, "v2")
    key_b_store = await storage.put(key_b, "v3")

    removed = await storage.remove(SampleKey(first="a", second="1"))

    assert set(removed) == {key_a1_store, key_a2_store}
    assert await storage.contains(SampleKey(first="a", second="1")) is False
    assert await storage.contains(SampleKey(first="a", second="2")) is True
    assert await storage.get_by_store_key(key_b_store) == "v3"


@pytest.mark.asyncio
async def test_query_pairs_skips_missing_values_and_keys():
    store = InMemoryStorage()
    storage = IndexStorage(store)

    key_one = SampleKey(first="g", second="1", third="x")
    key_two = SampleKey(first="g", second="1", third="y")

    store_one = await storage.put(key_one, "v1")
    store_two = await storage.put(key_two, "v2")

    await store.remove(store_one)
    storage._by_store_key.pop(store_two)

    result = await storage.query_pairs(SampleKey(first="g", second="1"))

    assert result == []


@pytest.mark.asyncio
async def test_query_returns_itemset_of_values():
    store = InMemoryStorage()
    storage = IndexStorage(store)

    key_one = SampleKey(first="g", second="1", third="x")
    key_two = SampleKey(first="g", second="1", third="y")

    store_one = await storage.put(key_one, "v1")
    await storage.put(key_two, "v2")

    await store.remove(store_one)

    result = await storage.query(SampleKey(first="g", second="1"))

    assert isinstance(result, ItemSet)
    assert set(result) == {"v2"}


@pytest.mark.asyncio
async def test_query_grouped_returns_subtree_and_leaf_itemset():
    store = InMemoryStorage()
    storage = IndexStorage(store)

    key_x = SampleKey(first="g", second="1", third="x")
    key_y = SampleKey(first="g", second="1", third="y")
    key_z = SampleKey(first="g", second="2", third="z")

    await storage.put(key_x, "vx")
    await storage.put(key_y, "vy")
    await storage.put(key_z, "vz")

    subtree = await storage.query_grouped(SampleKey(first="g"))

    assert set(subtree.keys()) == {"1", "2"}
    assert set(subtree["1"].keys()) == {"x", "y"}
    assert subtree["2"]["z"] == ItemSet(["vz"])

    leaf = await storage.query_grouped(SampleKey(first="g", second="1", third="x"))

    assert leaf == ItemSet(["vx"])


@pytest.mark.asyncio
async def test_query_grouped_returns_empty_itemset_for_missing_node_with_exact_key():
    store = InMemoryStorage()
    storage = IndexStorage(store)

    store_key = IndexStorage._make_store_key(("sample_key", "a", "b"))
    storage._by_store_key[store_key] = SampleKey(first="a", second="b")

    result = await storage.query_grouped(SampleKey(first="a", second="b"))

    assert result == ItemSet()


@pytest.mark.asyncio
async def test_keys_clear_and_reindex():
    store = InMemoryStorage()
    storage = IndexStorage(store)

    key_one = SampleKey(first="g", second="1", third="x")
    key_two = SampleKey(first="g", second="2", third="y")

    await storage.put(key_one, "v1")

    await storage.reindex([(key_two, "v2")])

    keys = await storage.keys()

    assert keys == [(IndexStorage._make_store_key(("sample_key", "g", "2", "y")), key_two)]
    assert await storage.contains(SampleKey(first="g", second="1")) is False
    assert await storage.contains(SampleKey(first="g", second="2")) is True

    await storage.clear()

    assert await storage.keys() == []
    assert await store.keys() == []


def test_separator_validation():
    store = InMemoryStorage()

    with pytest.raises(ValueError):
        IndexStorage(store, separator="")


def test_dask_tokenize_returns_separator():
    store = InMemoryStorage()
    storage = IndexStorage(store, separator="|")

    assert storage.__dask_tokenize__() == ("|",)
