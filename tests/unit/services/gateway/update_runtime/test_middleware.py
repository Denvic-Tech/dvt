from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport, AsyncClient

from services.gateway.update_runtime.middleware import SystemUpdateMiddleware
from services.gateway.update_runtime.monitor import SystemStateSnapshot

from src.schemas.http.system import SystemStateValue


class FakeMonitor:
    def __init__(self, state: SystemStateValue):
        self.state = state

    @property
    def snapshot(self) -> SystemStateSnapshot:
        return SystemStateSnapshot(
            state=self.state,
            retry_after_sec=3,
            checked_at=datetime.now(UTC),
        )


def _app(monitor: FakeMonitor) -> FastAPI:
    app = FastAPI()

    @app.api_route("/{path:path}", methods=["GET", "POST", "OPTIONS"])
    async def endpoint(path: str) -> dict[str, str]:
        return {"path": path}

    app.add_middleware(SystemUpdateMiddleware, monitor=monitor)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://ui.test"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app


@pytest.mark.asyncio
async def test_business_request_is_blocked_with_registered_error_and_cors() -> None:
    app = _app(FakeMonitor(SystemStateValue.UPDATING))
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/projects", headers={"Origin": "http://ui.test"})

    assert response.status_code == 503
    assert response.headers["retry-after"] == "3"
    assert response.headers["access-control-allow-origin"] == "http://ui.test"
    assert response.json()["code"] == "SYSTEM_UPDATING"
    assert response.json()["exc_data"] == {"retry_after": 3}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["/health", "/system/state", "/update/status", "/auth/check-auth", "/metrics"],
)
async def test_allowed_paths_are_not_blocked(path: str) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app(FakeMonitor(SystemStateValue.UPDATING))),
        base_url="http://test",
    ) as client:
        response = await client.get(path)

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_options_is_not_blocked() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app(FakeMonitor(SystemStateValue.UPDATING))),
        base_url="http://test",
    ) as client:
        response = await client.options(
            "/projects",
            headers={
                "Origin": "http://ui.test",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [SystemStateValue.READY, SystemStateValue.DEGRADED])
async def test_non_updating_states_do_not_block(state: SystemStateValue) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_app(FakeMonitor(state))),
        base_url="http://test",
    ) as client:
        response = await client.get("/projects")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_root_path_is_removed_before_allowlist_check() -> None:
    app = _app(FakeMonitor(SystemStateValue.UPDATING))
    async with AsyncClient(
        transport=ASGITransport(app=app, root_path="/api"),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/system/state")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_websocket_is_closed_with_try_again_later() -> None:
    messages: list[dict] = []

    async def downstream(scope, receive, send) -> None:
        raise AssertionError("downstream websocket app must not be called")

    async def send(message: dict) -> None:
        messages.append(message)

    middleware = SystemUpdateMiddleware(
        downstream,
        monitor=FakeMonitor(SystemStateValue.UPDATING),  # type: ignore[arg-type]
    )
    await middleware(
        {"type": "websocket", "path": "/ws", "root_path": ""},  # type: ignore[arg-type]
        lambda: None,  # type: ignore[arg-type]
        send,  # type: ignore[arg-type]
    )

    assert messages == [
        {
            "type": "websocket.close",
            "code": 1013,
            "reason": "DVT is being updated",
        }
    ]
