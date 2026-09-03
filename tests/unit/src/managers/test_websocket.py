import asyncio

import pytest

from src.managers.websocket import WebSocketManager
from src.schemas.event import PingEvent


@pytest.mark.asyncio
async def test_send_sync_captures_running_loop_and_sends_personal_message(monkeypatch):
    manager = WebSocketManager()
    message = PingEvent()

    event = asyncio.Event()
    calls = []

    async def fake_send_personal_message(*, message, user_id, project_id):
        calls.append((message, user_id, project_id))
        event.set()

    monkeypatch.setattr(manager, "send_personal_message", fake_send_personal_message)

    manager.send_sync(message=message, user_id="user-1", project_id="project-1")

    await asyncio.wait_for(event.wait(), timeout=1)

    assert manager._loop is asyncio.get_running_loop()
    assert calls == [(message, "user-1", "project-1")]


def test_send_sync_without_running_loop_does_not_raise():
    manager = WebSocketManager()

    manager.send_sync(message=PingEvent(), user_id="user-1", project_id="project-1")
