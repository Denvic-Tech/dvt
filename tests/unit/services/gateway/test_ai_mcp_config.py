import pytest
from fastapi import HTTPException

from services.gateway.deps.ai_mcp import require_ai_mcp_enabled

import config


def test_ai_mcp_validation_is_skipped_while_disabled(monkeypatch) -> None:
    monkeypatch.setattr(config.AI_MCP, "ENABLED", False)
    monkeypatch.setattr(config.AI_MCP, "INTERNAL_SECRET", "")

    config.AI_MCP.validate()


def test_ai_mcp_validation_requires_secret_while_enabled(monkeypatch) -> None:
    monkeypatch.setattr(config.AI_MCP, "ENABLED", True)
    monkeypatch.setattr(config.AI_MCP, "INTERNAL_SECRET", "short")

    with pytest.raises(RuntimeError, match="at least 32"):
        config.AI_MCP.validate()


def test_ai_mcp_routes_remain_registered_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(config.AI_MCP, "ENABLED", False)

    from services.gateway.main_router import router

    paths = {route.path for route in router.routes}
    assert any(path.startswith("/mcp-tokens") for path in paths)
    assert any(path.startswith("/internal/ai-mcp/") for path in paths)


def test_ai_mcp_routes_reject_requests_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(config.AI_MCP, "ENABLED", False)

    with pytest.raises(HTTPException) as exc_info:
        require_ai_mcp_enabled()

    assert exc_info.value.status_code == 503
