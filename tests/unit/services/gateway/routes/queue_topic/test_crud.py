from __future__ import annotations

from typing import Any

import pytest

from core.types import Column, DataType


@pytest.mark.asyncio
async def test_list_queue_topics_returns_items(
    gateway_client,
    router_prefix,
    test_queue_topic,
    other_queue_topic,
):
    response = await gateway_client.get(f"{router_prefix}/queue-topics")

    assert response.status_code == 200
    payload = response.json()
    assert {item["id"] for item in payload} == {test_queue_topic.id, other_queue_topic.id}


@pytest.mark.asyncio
async def test_list_queue_topics_filters_by_name(
    gateway_client,
    router_prefix,
    test_queue_topic,
    other_queue_topic,
):
    response = await gateway_client.get(
        f"{router_prefix}/queue-topics",
        params={"name": test_queue_topic.name},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload] == [test_queue_topic.id]


@pytest.mark.asyncio
async def test_get_queue_topic_returns_item(
    gateway_client,
    router_prefix,
    test_queue_topic,
):
    response = await gateway_client.get(
        f"{router_prefix}/queue-topics/{test_queue_topic.id}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == test_queue_topic.id
    assert payload["name"] == test_queue_topic.name
    assert payload["columns_schema"]


@pytest.mark.asyncio
async def test_get_queue_topic_missing_returns_404(
    gateway_client,
    router_prefix,
):
    response = await gateway_client.get(
        f"{router_prefix}/queue-topics/missing-topic"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_queue_topic_persists(
    gateway_client,
    router_prefix,
):
    columns = _columns_payload(
        [
            Column(name="id", dtype=DataType.INT, nullable=False, index=True),
            Column(name="payload", dtype=DataType.STRING, nullable=True),
        ]
    )
    payload = {
        "name": "topic-new",
        "columns_schema": columns,
    }

    response = await gateway_client.post(
        f"{router_prefix}/queue-topics",
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["id"]
    assert data["name"] == payload["name"]
    assert len(data["columns_schema"]) == len(columns)


@pytest.mark.asyncio
async def test_update_queue_topic_updates_fields(
    gateway_client,
    router_prefix,
    test_queue_topic,
):
    updated_columns = _columns_payload(
        [
            Column(name="id", dtype=DataType.INT, nullable=False, index=True),
            Column(name="payload", dtype=DataType.STRING, nullable=True),
            Column(name="created_at", dtype=DataType.DATETIME, nullable=False),
        ]
    )
    payload = {
        "name": "topic-updated",
        "columns_schema": updated_columns,
    }

    response = await gateway_client.patch(
        f"{router_prefix}/queue-topics/{test_queue_topic.id}",
        json=payload,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == payload["name"]
    assert len(data["columns_schema"]) == len(updated_columns)


@pytest.mark.asyncio
async def test_delete_queue_topic_removes(
    gateway_client,
    router_prefix,
    test_queue_topic,
):
    response = await gateway_client.delete(
        f"{router_prefix}/queue-topics/{test_queue_topic.id}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True

    response = await gateway_client.get(
        f"{router_prefix}/queue-topics/{test_queue_topic.id}"
    )

    assert response.status_code == 404


def _columns_payload(columns: list[Column]) -> list[dict[str, Any]]:
    return [column.model_dump(mode="json") for column in columns]
