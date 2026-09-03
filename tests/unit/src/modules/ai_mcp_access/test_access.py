from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from src.modules.ai_mcp_access.domain import (
    ExpiredMCPTokenError,
    InvalidMCPTokenError,
    MCPAccessScope,
    MCPToken,
    ResourceScope,
    ResourceScopeMode,
    RevokedMCPTokenError,
    digest_token,
    parse_token_id,
    verify_token,
)
from src.modules.ai_mcp_access.flow import AuthenticateMCPToken, CreateMCPToken


class InMemoryTokenRepository:
    def __init__(self) -> None:
        self.tokens: dict[str, MCPToken] = {}

    async def get_by_id(self, token_id: str) -> MCPToken | None:
        return self.tokens.get(token_id)

    async def get_for_user(self, token_id: str, user_id: str) -> MCPToken | None:
        token = self.tokens.get(token_id)
        return token if token is not None and token.user_id == user_id else None

    async def list_for_user(self, user_id: str) -> list[MCPToken]:
        return [token for token in self.tokens.values() if token.user_id == user_id]

    async def save(self, token: MCPToken) -> MCPToken:
        self.tokens[token.id] = token
        return token


def _scope() -> MCPAccessScope:
    return MCPAccessScope(
        projects=ResourceScope(ResourceScopeMode.ALL),
        db_connections=ResourceScope(
            ResourceScopeMode.SELECTED,
            frozenset({"connection-a"}),
        ),
    )


def test_scope_all_includes_future_resources_and_selected_is_exact() -> None:
    scope = _scope()

    assert scope.allows_project("future-project")
    assert scope.allows_connection("connection-a")
    assert not scope.allows_connection("connection-b")
    assert scope.to_mapping() == {
        "schema_version": 1,
        "purpose": "mcp",
        "projects": {"mode": "all", "ids": []},
        "db_connections": {"mode": "selected", "ids": ["connection-a"]},
    }


@pytest.mark.asyncio
async def test_created_token_has_256_bit_secret_and_only_digest_is_persisted() -> None:
    repository = InMemoryTokenRepository()

    result = await CreateMCPToken(repository).execute(
        user_id="user-a",
        name="Codex",
        access_scope=_scope(),
        expires_at=None,
    )

    assert result.raw_token.startswith(f"dvt_mcp_{result.token.id}.")
    assert parse_token_id(result.raw_token) == result.token.id
    assert result.token.token_digest == digest_token(result.raw_token)
    assert result.raw_token not in result.token.token_digest
    assert len(result.raw_token.rsplit(".", 1)[1]) >= 40
    authenticated = await AuthenticateMCPToken(repository).execute(raw_token=result.raw_token)
    assert authenticated.id == result.token.id


def test_digest_verification_distinguishes_invalid_expired_and_revoked() -> None:
    raw = "dvt_mcp_00000000-0000-0000-0000-000000000000." + "a" * 43
    token = MCPToken(
        id=parse_token_id(raw),
        user_id="user-a",
        token_digest=digest_token(raw),
        name=None,
        access_scope=_scope(),
        created_at=datetime.now(UTC),
    )

    verify_token(token, raw, now_epoch=100)
    with pytest.raises(InvalidMCPTokenError):
        verify_token(token, raw[:-1] + "b", now_epoch=100)
    with pytest.raises(ExpiredMCPTokenError):
        verify_token(replace(token, expires_at=100), raw, now_epoch=100)
    with pytest.raises(RevokedMCPTokenError):
        verify_token(replace(token, is_deleted=True), raw, now_epoch=100)
