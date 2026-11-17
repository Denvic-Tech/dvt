from services.gateway.routes.agents import render


def test_instruction_substitutes_every_placeholder() -> None:
    text = render.render_instruction("https://dvt.example.com", "K7F3-9QZX")

    assert "{{" not in text
    assert "DVT dvt.example.com" in text
    assert "https://dvt.example.com/mcp" in text
    assert "https://dvt.example.com/api/agents/claim/K7F3-9QZX" in text
    assert "dvt_mcp_" not in text


def test_links_are_built_from_the_given_origin() -> None:
    assert render.connect_url("http://dvt.local", "AAAA-BBBB") == (
        "http://dvt.local/api/agents/connect/AAAA-BBBB.md"
    )
    assert render.claim_url("http://dvt.local", "AAAA-BBBB") == (
        "http://dvt.local/api/agents/claim/AAAA-BBBB"
    )
    assert render.mcp_url("http://dvt.local") == "http://dvt.local/mcp"


def test_agent_routes_are_registered_under_agents_prefix() -> None:
    from services.gateway.main_router import router

    paths = {route.path for route in router.routes}
    assert {"/agents/connect", "/agents/claim/{code}", "/agents/connect/{code}.md"} <= paths
    assert not any(path.startswith("/agents/skills") for path in paths)
