from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from src.modules.ai_mcp_access.domain.value_objects import MCPAccessScope


class ConnectCodeStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class AgentConnectCode:
    """A short-lived request to connect an AI agent to this DVT.

    The public code itself is never stored: only its digest. Each claim issues a fresh MCP
    token for ``user_id`` with ``access_scope`` and revokes the token of the previous claim.
    ``public_url`` is the origin the user opened DVT from; every link in the instruction is
    built from it.
    """

    id: str
    code_digest: str
    user_id: str
    access_scope: MCPAccessScope
    public_url: str
    created_at: datetime
    expires_at: datetime
    token_name: str | None = None
    token_expires_at: int | None = None
    token_id: str | None = None
    claims_count: int = 0
    last_claimed_at: datetime | None = None
    is_revoked: bool = False
