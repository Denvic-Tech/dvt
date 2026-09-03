from pathlib import Path


def test_mcp_route_is_guarded_by_disabled_by_default_flag() -> None:
    caddyfile = (
        Path(__file__).resolve().parents[4] / "services" / "proxy" / "Caddyfile"
    ).read_text(encoding="utf-8")

    assert "{$DVT_AI_MCP_ENABLED:false} == true" in caddyfile
    assert "{$DVT_AI_MCP_ENABLED:false} != true" in caddyfile
    assert 'respond @mcp_disabled "Not Found" 404' in caddyfile
