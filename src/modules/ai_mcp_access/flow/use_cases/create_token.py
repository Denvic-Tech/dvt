from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from ...domain.entities import MCPToken
from ...domain.policies import digest_token
from ...domain.repositories import MCPTokenRepository
from ...domain.types import MCP_TOKEN_PREFIX
from ...domain.value_objects import MCPAccessScope


@dataclass(frozen=True, slots=True)
class CreatedMCPToken:
    token: MCPToken
    raw_token: str


class CreateMCPToken:
    def __init__(self, repository: MCPTokenRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        *,
        user_id: str,
        name: str | None,
        access_scope: MCPAccessScope,
        expires_at: int | None,
    ) -> CreatedMCPToken:
        token_id = str(uuid4())
        raw_token = f"{MCP_TOKEN_PREFIX}{token_id}.{secrets.token_urlsafe(32)}"
        token = MCPToken(
            id=token_id,
            user_id=user_id,
            token_digest=digest_token(raw_token),
            name=name.strip() if name else None,
            access_scope=access_scope,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        saved = await self._repository.save(token)
        return CreatedMCPToken(token=saved, raw_token=raw_token)
