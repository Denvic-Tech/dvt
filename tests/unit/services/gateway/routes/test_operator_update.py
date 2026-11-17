from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.gateway.routes.installation import update
from services.gateway.update_runtime import operator

from src.modules.user.infra.fastapi import dependencies


def test_operator_updates_enforce_superadmin_and_csrf_before_forwarding(monkeypatch):
    app = FastAPI()
    app.include_router(update.router)
    origin = "https://dvt.example.com"
    role = SimpleNamespace(role="user", is_active=True, is_verified=True)
    app.dependency_overrides[dependencies.usrak_get_user_access_only] = lambda: role
    monkeypatch.setattr(operator.config.GATEWAY, "GATEWAY_ORIGINS", [origin])
    bridge = AsyncMock(return_value=httpx.Response(202, json={
        "id": "97f89dfa-1a89-4783-86a6-6d173dc4b5d4",
        "kind": "update", "version": "1.2.3",
        "manifest_digest": "sha256:" + "a" * 64, "stage": "prepared",
        "failure": None, "actions": ["apply"], "plan": None,
        "created_at": "2026-01-01T00:00:00Z", "finished_at": None,
    }))
    monkeypatch.setattr(update, "operator_request", bridge)
    client = TestClient(app)
    body = {"kind": "update", "version": "1.2.3", "manifest_digest": "sha256:" + "a" * 64}
    csrf = {"Origin": origin, "X-DVT-CSRF": "1", "Idempotency-Key": "only-once"}
    assert client.post("/update/operations", json=body, headers=csrf).status_code == 403
    role.role = "superadmin"
    assert client.post("/update/operations", json=body, headers={
        **csrf, "Origin": "https://wrong.example.com",
    }).status_code == 403
    assert client.post("/update/operations", json=body, headers={
        "Origin": origin, "Idempotency-Key": "only-once",
    }).status_code == 403
    bridge.assert_not_called()

    result = client.post("/update/operations", json=body, headers=csrf)
    assert result.status_code == 202
    assert result.json()["actions"] == ["apply"]
    assert bridge.await_args.kwargs["headers"] == {"Idempotency-Key": "only-once"}
    assert bridge.await_args.kwargs["json"]["manifest_digest"] == body["manifest_digest"]
