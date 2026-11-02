"""End-to-end flow of agent connection links: create, read the instruction, claim, revoke."""

from __future__ import annotations

import pytest

import config

pytestmark = [pytest.mark.docker_required, pytest.mark.asyncio(loop_scope="session")]

SCOPE = {
    "schema_version": 1,
    "purpose": "mcp",
    "projects": {"mode": "all", "ids": []},
    "db_connections": {"mode": "selected", "ids": ["conn-a"]},
}


@pytest.fixture
def agent_connect_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.AI_MCP, "ENABLED", True)
    monkeypatch.setattr(config.GATEWAY, "GATEWAY_ORIGINS", ["http://dvt.test", "https://dvt.corp"])
    monkeypatch.setattr(config.AGENT_CONNECT, "MAX_CLAIMS", 2)


async def test_link_lifecycle(
    agent_connect_env: None,
    gateway_client,
    router_prefix: str,
) -> None:
    created = await gateway_client.post(
        f"{router_prefix}/agents/connect",
        json={"base_url": "http://dvt.test/", "access_scope": SCOPE, "name": "Claude Code"},
    )
    assert created.status_code == 201, created.text
    link = created.json()
    code = link["code"]
    assert link["connect_url"] == f"http://dvt.test/api/agents/connect/{code}.md"

    listed = await gateway_client.get(f"{router_prefix}/agents/connect")
    assert [item["status"] for item in listed.json()["items"]] == ["pending"]

    # The instruction carries no secret, only the claim address (anonymity: see the next test).
    instruction = await gateway_client.get(f"{router_prefix}/agents/connect/{code}.md")
    assert instruction.status_code == 200
    assert instruction.headers["content-type"].startswith("text/markdown")
    assert f"http://dvt.test/api/agents/claim/{code}" in instruction.text
    assert "dvt_mcp_" not in instruction.text

    # Each claim issues a fresh token and revokes the previous one.
    first = await gateway_client.get(f"{router_prefix}/agents/claim/{code}")
    assert first.status_code == 200 and first.text.startswith("dvt_mcp_")
    second = await gateway_client.get(f"{router_prefix}/agents/claim/{code}")
    assert second.status_code == 200 and second.text != first.text

    tokens = (await gateway_client.get(f"{router_prefix}/mcp-tokens")).json()["items"]
    assert [token["name"] for token in tokens] == ["Claude Code"]
    assert tokens[0]["access_scope"] == SCOPE
    assert second.text.startswith(f"dvt_mcp_{tokens[0]['id']}.")

    third = await gateway_client.get(f"{router_prefix}/agents/claim/{code}")
    assert third.status_code == 410

    listed = await gateway_client.get(f"{router_prefix}/agents/connect")
    item = listed.json()["items"][0]
    assert item["status"] == "claimed" and item["claims_count"] == 2
    assert item["token_id"] == tokens[0]["id"]

    # Revoking the link also revokes the token it issued.
    revoked = await gateway_client.delete(f"{router_prefix}/agents/connect/{link['id']}")
    assert revoked.status_code == 204
    assert (await gateway_client.get(f"{router_prefix}/mcp-tokens")).json()["items"] == []
    after = await gateway_client.get(f"{router_prefix}/agents/claim/{code}")
    assert after.status_code == 410
    gone = await gateway_client.get(f"{router_prefix}/agents/connect/{code}.md")
    assert gone.status_code == 404 and "недействительна" in gone.text
    assert (await gateway_client.get(f"{router_prefix}/agents/connect")).json()["items"][0][
        "status"
    ] == "revoked"


async def test_unknown_code_and_disabled_feature(
    agent_connect_env: None,
    unauthenticated_gateway_client,
    router_prefix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unknown = await unauthenticated_gateway_client.get(f"{router_prefix}/agents/claim/ZZZZ-ZZZZ")
    assert unknown.status_code == 404
    unknown_md = await unauthenticated_gateway_client.get(
        f"{router_prefix}/agents/connect/ZZZZ-ZZZZ.md"
    )
    assert unknown_md.status_code == 404

    monkeypatch.setattr(config.AI_MCP, "ENABLED", False)
    disabled = await unauthenticated_gateway_client.get(f"{router_prefix}/agents/claim/ZZZZ-ZZZZ")
    assert disabled.status_code == 503


async def test_base_url_outside_public_addresses_is_rejected(
    agent_connect_env: None,
    gateway_client,
    router_prefix: str,
) -> None:
    rejected = await gateway_client.post(
        f"{router_prefix}/agents/connect",
        json={"base_url": "http://evil.example", "access_scope": SCOPE},
    )
    assert rejected.status_code == 422
    assert "public address" in rejected.text

    accepted = await gateway_client.post(
        f"{router_prefix}/agents/connect",
        json={"base_url": "HTTPS://dvt.corp", "access_scope": SCOPE},
    )
    assert accepted.status_code == 201
    assert accepted.json()["connect_url"].startswith("https://dvt.corp/api/agents/connect/")
