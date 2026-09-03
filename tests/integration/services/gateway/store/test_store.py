import asyncio
from uuid import uuid4

import pytest


@pytest.fixture
def store_key_prefix() -> str:
    return f"store-{uuid4().hex}"


def _store_key(prefix: str, suffix: str) -> str:
    return f"{prefix}:{suffix}"


@pytest.mark.asyncio
async def test_store_set_string_success(gateway_client, router_prefix, store_key_prefix):
    """Проверка записи обычной строки"""
    key = _store_key(store_key_prefix, "test_string_key")
    value = "Hello, world! Привет, мир!"

    response = await gateway_client.post(
        f"{router_prefix}/store",
        params={"key": key},
        content=value
    )

    assert response.status_code == 201
    assert response.json()["key"] == key


@pytest.mark.asyncio
async def test_store_get_string_integrity(gateway_client, router_prefix, store_key_prefix):
    """Проверка, что возвращается та же строка, что была записана"""
    key = _store_key(store_key_prefix, "integrity_test")
    value = "Simple String 123"

    await gateway_client.post(
        f"{router_prefix}/store",
        params={"key": key},
        content=value
    )

    response = await gateway_client.get(
        f"{router_prefix}/store",
        params={"pattern": key}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload[key] == value  # Прямое сравнение строк


@pytest.mark.asyncio
async def test_store_pagination_strings(gateway_client, router_prefix, store_key_prefix):
    """Проверка пагинации на строковых данных"""
    prefix = _store_key(store_key_prefix, "pag_str")
    for i in range(4):
        await gateway_client.post(
            f"{router_prefix}/store",
            params={"key": f"{prefix}_{i}"},
            content=f"val_{i}"
        )

    # Страница 1
    resp1 = await gateway_client.get(
        f"{router_prefix}/store",
        params={"pattern": f"{prefix}_*", "limit": 2, "offset": 0}
    )
    # Страница 2
    resp2 = await gateway_client.get(
        f"{router_prefix}/store",
        params={"pattern": f"{prefix}_*", "limit": 2, "offset": 2}
    )

    assert len(resp1.json()) == 2
    assert len(resp2.json()) == 2
    assert set(resp1.json().keys()).isdisjoint(set(resp2.json().keys()))


@pytest.mark.asyncio
async def test_store_delete_pattern(gateway_client, router_prefix, store_key_prefix):
    """Удаление по паттерну"""
    key = _store_key(store_key_prefix, "delete_me_str")
    await gateway_client.post(f"{router_prefix}/store", params={"key": key}, content="data")

    resp = await gateway_client.delete(
        f"{router_prefix}/store",
        params={"pattern": f"{store_key_prefix}:delete_me*"},
    )
    assert resp.status_code == 200
    assert resp.json()["deleted_count"] >= 1


async def _wait_until_key_absent(gateway_client, router_prefix: str, key: str, timeout_sec: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_sec
    while True:
        get_resp = await gateway_client.get(f"{router_prefix}/store", params={"pattern": key})
        if key not in get_resp.json():
            return
        if asyncio.get_running_loop().time() >= deadline:
            break
        await asyncio.sleep(0.1)
    raise AssertionError(f"Key {key!r} is still present after waiting for TTL expiration")


@pytest.mark.asyncio
async def test_store_set_with_ttl(gateway_client, router_prefix, store_key_prefix):
    """Проверка записи одиночной строки с TTL"""
    key = _store_key(store_key_prefix, "ttl_test_key")
    value = "I will expire soon"
    ttl = 1

    # Записываем с TTL
    response = await gateway_client.post(
        f"{router_prefix}/store",
        params={"key": key, "ttl": ttl},
        content=value
    )
    assert response.status_code == 201
    assert response.json()["ttl"] == ttl

    # Проверяем, что данные есть
    get_resp = await gateway_client.get(f"{router_prefix}/store", params={"pattern": key})
    assert key in get_resp.json()

    await _wait_until_key_absent(gateway_client, router_prefix, key)


@pytest.mark.asyncio
async def test_store_batch_mset_success(gateway_client, router_prefix, store_key_prefix):
    """Проверка пакетной вставки через MSET (без TTL)"""
    batch_data = [
        {"key": _store_key(store_key_prefix, "batch_1"), "value": "val_1"},
        {"key": _store_key(store_key_prefix, "batch_2"), "value": "val_2"},
        {"key": _store_key(store_key_prefix, "batch_3"), "value": "val_3"},
    ]

    response = await gateway_client.post(
        f"{router_prefix}/store/batch",
        json=batch_data
    )

    assert response.status_code == 201
    assert response.json()["processed"] == 3
    assert response.json()["method"] == "mset"

    # Проверяем целостность одного из ключей
    get_resp = await gateway_client.get(
        f"{router_prefix}/store",
        params={"pattern": f"{store_key_prefix}:batch_*"},
    )
    assert get_resp.json()[_store_key(store_key_prefix, "batch_1")] == "val_1"
    assert len(get_resp.json()) == 3


@pytest.mark.asyncio
async def test_store_batch_pipeline_ttl_success(gateway_client, router_prefix, store_key_prefix):
    """Проверка пакетной вставки через Pipeline (с TTL)"""
    batch_data = [
        {"key": _store_key(store_key_prefix, "batch_ttl_1"), "value": "v1"},
        {"key": _store_key(store_key_prefix, "batch_ttl_2"), "value": "v2"},
    ]
    ttl = 5

    response = await gateway_client.post(
        f"{router_prefix}/store/batch",
        params={"ttl": ttl},
        json=batch_data
    )

    assert response.status_code == 201
    assert response.json()["method"] == "pipeline_with_ttl"

    # Проверяем наличие
    get_resp = await gateway_client.get(
        f"{router_prefix}/store",
        params={"pattern": f"{store_key_prefix}:batch_ttl_*"},
    )
    assert len(get_resp.json()) == 2
