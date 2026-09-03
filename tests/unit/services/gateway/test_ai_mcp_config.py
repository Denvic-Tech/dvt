import pytest

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


def test_ai_mcp_gateway_routes_are_absent_by_default() -> None:
    from services.gateway.main_router import router

    paths = {route.path for route in router.routes}
    assert not any(path.startswith("/mcp-tokens") for path in paths)
    assert not any(path.startswith("/internal/ai-mcp/") for path in paths)
