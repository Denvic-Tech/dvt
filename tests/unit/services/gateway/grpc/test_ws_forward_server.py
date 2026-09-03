from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from services.gateway.grpc import ws_forward_server as ws_forward_module
from services.gateway.grpc.ws_forward_server import ForwardWSServicer

from src.schemas.event import PingEvent


class _FailingWSManager:
    def __init__(self):
        self.calls = []

    def send_sync(self, *, message, user_id, project_id):
        self.calls.append((message, user_id, project_id))
        raise RuntimeError("event loop unavailable")


class _FakeContext:
    @staticmethod
    def peer():
        return "ipv4:127.0.0.1:0"


async def _request_iterator(*requests):
    for request in requests:
        yield request


@pytest.mark.asyncio
async def test_forward_stream_continues_when_ws_send_fails(monkeypatch):
    @asynccontextmanager
    async def fake_session_acm():
        yield object()

    async def fake_check(*_args, **_kwargs):
        return True

    monkeypatch.setattr(ws_forward_module, "get_async_session_acm", fake_session_acm)
    monkeypatch.setattr(ws_forward_module, "_check_project_belongs_to_user", fake_check)
    monkeypatch.setattr(ws_forward_module, "_parse_ws_message", lambda _payload: PingEvent())

    ws_manager = _FailingWSManager()
    servicer = ForwardWSServicer(ws_manager=ws_manager)

    request_1 = SimpleNamespace(user_id="user-1", project_id="project-1", payload_json="{}")
    request_2 = SimpleNamespace(user_id="user-1", project_id="project-1", payload_json="{}")

    ack = await servicer.ForwardStream(_request_iterator(request_1, request_2), _FakeContext())

    assert ack.ok is True
    assert len(ws_manager.calls) == 2


@pytest.mark.asyncio
async def test_forward_unary_returns_error_when_ws_send_fails(monkeypatch):
    @asynccontextmanager
    async def fake_session_acm():
        yield object()

    async def fake_check(*_args, **_kwargs):
        return True

    monkeypatch.setattr(ws_forward_module, "get_async_session_acm", fake_session_acm)
    monkeypatch.setattr(ws_forward_module, "_check_project_belongs_to_user", fake_check)
    monkeypatch.setattr(ws_forward_module, "_parse_ws_message", lambda _payload: PingEvent())

    ws_manager = _FailingWSManager()
    servicer = ForwardWSServicer(ws_manager=ws_manager)

    request = SimpleNamespace(user_id="user-1", project_id="project-1", payload_json="{}")

    ack = await servicer.ForwardUnary(request, _FakeContext())

    assert ack.ok is False
    assert "failed to forward message" in ack.error
    assert len(ws_manager.calls) == 1
