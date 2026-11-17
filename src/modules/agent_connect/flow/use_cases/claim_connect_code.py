from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from src.modules.ai_mcp_access.domain.exceptions import MCPTokenNotFoundError
from src.modules.ai_mcp_access.domain.repositories import MCPTokenRepository
from src.modules.ai_mcp_access.flow import CreateMCPToken, RevokeMCPToken

from ...domain.entities import AgentConnectCode
from ...domain.exceptions import ConnectCodeNotFoundError
from ...domain.policies import digest_code, ensure_claimable
from ...domain.repositories import AgentConnectCodeRepository


@dataclass(frozen=True, slots=True)
class ClaimedConnectCode:
    code: AgentConnectCode
    raw_token: str


class ClaimConnectCode:
    """Exchange a public code for an MCP token.

    Every claim issues a new token and revokes the one from the previous claim, so an agent
    whose first attempt to store the token failed can simply retry, and no raw token is ever
    kept on the server.
    """

    def __init__(
        self,
        codes: AgentConnectCodeRepository,
        tokens: MCPTokenRepository,
        *,
        max_claims: int,
        record_ttl_seconds: int,
    ) -> None:
        self._codes = codes
        self._tokens = tokens
        self._max_claims = max_claims
        self._record_ttl_seconds = record_ttl_seconds

    async def execute(self, *, raw_code: str, now: datetime | None = None) -> ClaimedConnectCode:
        moment = now or datetime.now(UTC)
        code = await self._codes.get_by_digest(digest_code(raw_code))
        if code is None:
            raise ConnectCodeNotFoundError("Connection link not found.")
        ensure_claimable(code, moment, max_claims=self._max_claims)

        if code.token_id is not None:
            with suppress(MCPTokenNotFoundError):
                await RevokeMCPToken(self._tokens).execute(
                    token_id=code.token_id,
                    user_id=code.user_id,
                )

        created = await CreateMCPToken(self._tokens).execute(
            user_id=code.user_id,
            name=code.token_name or _default_token_name(moment),
            access_scope=code.access_scope,
            expires_at=code.token_expires_at,
        )
        updated = await self._codes.save(
            replace(
                code,
                token_id=created.token.id,
                claims_count=code.claims_count + 1,
                last_claimed_at=moment,
            ),
            ttl_seconds=self._record_ttl_seconds,
        )
        return ClaimedConnectCode(code=updated, raw_token=created.raw_token)


def _default_token_name(moment: datetime) -> str:
    return f"Agent connect {moment.strftime('%Y-%m-%d %H:%M')} UTC"
