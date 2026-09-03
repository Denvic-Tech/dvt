from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError

import services.orchestrator.listeners.events as events_module
import services.orchestrator.listeners.heartbeat as heartbeat_module


class _FakeEventsRedis:
    def __init__(self, *, xread_behaviors: list[object]) -> None:
        self._xread_behaviors = list(xread_behaviors)
        self.xgroup_create_calls: list[dict[str, object]] = []
        self.xack_calls: list[tuple[object, ...]] = []
        self._dedupe_keys: set[str] = set()
        self.closed = False

    async def xgroup_create(self, **kwargs) -> None:
        self.xgroup_create_calls.append(kwargs)

    async def xreadgroup(self, **_kwargs):
        behavior = self._xread_behaviors.pop(0)
        if callable(behavior):
            behavior = behavior()
        if isinstance(behavior, Exception):
            raise behavior
        return behavior

    async def xautoclaim(self, **_kwargs):
        return "0-0", [], []

    async def xack(self, *args) -> None:
        self.xack_calls.append(args)

    async def set(self, key, _value, *, nx=False, ex=None):
        del ex
        if nx and key in self._dedupe_keys:
            return False
        self._dedupe_keys.add(key)
        return True

    async def close(self) -> None:
        self.closed = True


class _FakePubSub:
    def __init__(self, *, listen_behavior: object) -> None:
        self._listen_behavior = listen_behavior
        self.subscribe_calls: list[str] = []
        self.closed = False

    async def subscribe(self, channel: str) -> None:
        self.subscribe_calls.append(channel)

    async def close(self) -> None:
        self.closed = True

    async def listen(self):
        behavior = self._listen_behavior
        if callable(behavior):
            behavior = behavior()
        if isinstance(behavior, Exception):
            raise behavior
        for item in behavior:
            yield item


class _FakeHeartbeatRedis:
    def __init__(self, *, pubsub: _FakePubSub) -> None:
        self._pubsub = pubsub
        self.closed = False

    def pubsub(self) -> _FakePubSub:
        return self._pubsub

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_events_notification_reservation_is_idempotent_by_stream_message_id():
    listener = events_module.EventsStreamListener()
    listener._redis = _FakeEventsRedis(xread_behaviors=[])

    assert await listener._reserve_notification_delivery("123-0") is True
    assert await listener._reserve_notification_delivery("123-0") is False
    assert await listener._reserve_notification_delivery("124-0") is True


@pytest.mark.asyncio
async def test_events_listener_recreates_group_after_nogroup(monkeypatch):
    listener = events_module.EventsStreamListener()

    def _stop_listening():
        listener._shutdown_event.set()
        return []

    client = _FakeEventsRedis(
        xread_behaviors=[
            ResponseError("NOGROUP No such key 'orchestrator.events'"),
            _stop_listening,
        ]
    )

    monkeypatch.setattr(events_module.redis, "Redis", lambda **_kwargs: client)
    monkeypatch.setattr(events_module, "handle_worker_event", AsyncMock())

    await listener._listen()

    assert len(client.xgroup_create_calls) == 2


@pytest.mark.asyncio
async def test_events_listener_reconnects_after_connection_error(monkeypatch):
    listener = events_module.EventsStreamListener()

    def _stop_listening():
        listener._shutdown_event.set()
        return []

    first_client = _FakeEventsRedis(
        xread_behaviors=[RedisConnectionError("Connection closed by server")]
    )
    second_client = _FakeEventsRedis(xread_behaviors=[_stop_listening])
    clients = iter([first_client, second_client])

    monkeypatch.setattr(events_module.redis, "Redis", lambda **_kwargs: next(clients))
    monkeypatch.setattr(events_module, "handle_worker_event", AsyncMock())
    monkeypatch.setattr(listener, "_wait_before_retry", AsyncMock())

    await listener._listen()

    assert first_client.closed is True
    assert len(first_client.xgroup_create_calls) == 1
    assert len(second_client.xgroup_create_calls) == 1


@pytest.mark.asyncio
async def test_heartbeat_listener_reconnects_and_resubscribes(monkeypatch):
    listener = heartbeat_module.HeartbeatListener()

    first_pubsub = _FakePubSub(
        listen_behavior=RedisConnectionError("Connection closed by server")
    )
    second_pubsub = _FakePubSub(
        listen_behavior=[
            {"type": "subscribe", "data": 1},
            {
                "type": "message",
                "data": (
                    '{"worker_id":"worker-1","capabilities":["full"],'
                    '"max_concurrent":2,"timestamp":123.0,"system_info":null}'
                ),
            },
        ]
    )
    first_client = _FakeHeartbeatRedis(pubsub=first_pubsub)
    second_client = _FakeHeartbeatRedis(pubsub=second_pubsub)
    clients = iter([first_client, second_client])

    registry = type("Registry", (), {})()
    registry.update_from_heartbeat = AsyncMock(
        side_effect=lambda **_kwargs: listener._shutdown_event.set()
    )

    monkeypatch.setattr(heartbeat_module.redis, "Redis", lambda **_kwargs: next(clients))
    monkeypatch.setattr(heartbeat_module, "get_worker_registry", lambda: registry)
    monkeypatch.setattr(listener, "_wait_before_retry", AsyncMock())

    await listener._listen()

    assert first_client.closed is True
    assert first_pubsub.closed is True
    assert second_pubsub.subscribe_calls == [heartbeat_module.config.CELERY.CELERY_HEARTBEAT_CHANNEL]
    registry.update_from_heartbeat.assert_awaited_once()
