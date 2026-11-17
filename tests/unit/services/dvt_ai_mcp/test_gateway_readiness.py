from dataclasses import replace

import httpx
import pytest


@pytest.mark.parametrize(
    ("status", "code", "ready"),
    [(401, "AUTH_INVALID", True), (401, "INTERNAL_AUTH_FAILED", False), (404, None, False)],
)
async def test_mcp_readiness_requires_gateway_to_accept_the_internal_secret(
    monkeypatch, status, code, ready
):
    monkeypatch.setenv("ENVIRONMENT", "test")
    from services.dvt_ai_mcp import gateway_client

    expected = "fixture-internal-secret"
    monkeypatch.setattr(
        gateway_client, "settings", replace(gateway_client.settings, internal_secret=expected)
    )
    client = gateway_client.GatewayClient()

    def verify(request):
        assert request.url.path == "/internal/ai-mcp/v1/auth/verify"
        assert request.headers["X-DVT-AI-MCP-Internal-Secret"] == expected
        assert "Authorization" not in request.headers
        return httpx.Response(status, json={"detail": {"code": code}})

    await client._client.aclose()
    async with httpx.AsyncClient(
        base_url="http://gateway", transport=httpx.MockTransport(verify)
    ) as http:
        monkeypatch.setattr(client, "_client", http)
        assert await client.upstream_ready() is ready
