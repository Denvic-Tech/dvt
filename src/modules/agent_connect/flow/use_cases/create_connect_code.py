from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from src.modules.ai_mcp_access.domain.value_objects import MCPAccessScope

from ...domain.entities import AgentConnectCode
from ...domain.policies import digest_code, generate_code
from ...domain.repositories import AgentConnectCodeRepository


@dataclass(frozen=True, slots=True)
class CreatedConnectCode:
    code: AgentConnectCode
    raw_code: str


class CreateConnectCode:
    def __init__(self, repository: AgentConnectCodeRepository, *, code_ttl_seconds: int) -> None:
        self._repository = repository
        self._code_ttl_seconds = code_ttl_seconds

    async def execute(
        self,
        *,
        user_id: str,
        access_scope: MCPAccessScope,
        public_url: str,
        token_name: str | None,
        token_expires_at: int | None,
        now: datetime | None = None,
    ) -> CreatedConnectCode:
        created_at = now or datetime.now(UTC)
        raw_code = generate_code()
        code = AgentConnectCode(
            id=str(uuid4()),
            code_digest=digest_code(raw_code),
            user_id=user_id,
            access_scope=access_scope,
            public_url=public_url,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=self._code_ttl_seconds),
            token_name=token_name.strip() if token_name and token_name.strip() else None,
            token_expires_at=token_expires_at,
        )
        saved = await self._repository.save(code, ttl_seconds=self._code_ttl_seconds)
        return CreatedConnectCode(code=saved, raw_code=raw_code)
