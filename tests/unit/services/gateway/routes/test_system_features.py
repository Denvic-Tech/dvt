import pytest

import config


@pytest.mark.asyncio
async def test_get_runtime_config_returns_ai_analysis_flag(
    gateway_client,
    router_prefix,
    monkeypatch,
):
    monkeypatch.setattr(config.AI_ANALYSIS, "ENABLED", True)

    response = await gateway_client.get(f"{router_prefix}/system/runtime-config")

    assert response.status_code == 200, response.json()
    assert response.json() == {"features": {"ai_analysis": True}}
