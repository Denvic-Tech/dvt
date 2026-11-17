from __future__ import annotations

from contextlib import suppress
from dataclasses import replace

from src.modules.ai_mcp_access.domain.exceptions import MCPTokenNotFoundError
from src.modules.ai_mcp_access.domain.repositories import MCPTokenRepository
from src.modules.ai_mcp_access.flow import RevokeMCPToken

from ...domain.entities import AgentConnectCode
from ...domain.exceptions import ConnectCodeNotFoundError
from ...domain.repositories import AgentConnectCodeRepository


class RevokeConnectCode:
    """Revoke a connection link and, when it was already claimed, the token it issued."""

    def __init__(
        self,
        codes: AgentConnectCodeRepository,
        tokens: MCPTokenRepository,
        *,
        record_ttl_seconds: int,
    ) -> None:
        self._codes = codes
        self._tokens = tokens
        self._record_ttl_seconds = record_ttl_seconds

    async def execute(self, *, code_id: str, user_id: str) -> AgentConnectCode:
        code = await self._codes.get_for_user(code_id, user_id)
        if code is None:
            raise ConnectCodeNotFoundError("Connection link not found.")
        if code.token_id is not None:
            with suppress(MCPTokenNotFoundError):
                await RevokeMCPToken(self._tokens).execute(token_id=code.token_id, user_id=user_id)
        return await self._codes.save(
            replace(code, is_revoked=True),
            ttl_seconds=self._record_ttl_seconds,
        )
