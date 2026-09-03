from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header

from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.ai_mcp_access.domain import (
    ExpiredMCPTokenError,
    InvalidMCPTokenError,
    MCPToken,
    RevokedMCPTokenError,
)
from src.modules.ai_mcp_access.flow import AuthenticateMCPToken
from src.modules.ai_mcp_access.infra import SQLAlchemyMCPTokenRepository
from src.modules.user.infra.db_models import UserRecord

import config

from .errors import AIMCPHTTPError


@dataclass(frozen=True, slots=True)
class MCPPrincipal:
    user: UserRecord
    token: MCPToken

    def allows_project(self, project_id: str) -> bool:
        return self.token.access_scope.allows_project(project_id)

    def allows_connection(self, connection_id: str) -> bool:
        return self.token.access_scope.allows_connection(connection_id)


async def get_mcp_principal(
    session: AsyncSessionDepends,
    authorization: Annotated[str | None, Header()] = None,
    internal_secret: Annotated[
        str | None,
        Header(alias="X-DVT-AI-MCP-Internal-Secret"),
    ] = None,
) -> MCPPrincipal:
    expected_secret = config.AI_MCP.INTERNAL_SECRET
    if not internal_secret or not hmac.compare_digest(internal_secret, expected_secret):
        raise AIMCPHTTPError(401, "INTERNAL_AUTH_FAILED", "Internal authentication failed.")

    scheme, _, raw_token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not raw_token:
        raise AIMCPHTTPError(401, "AUTH_INVALID", "A valid MCP bearer token is required.")

    try:
        token = await AuthenticateMCPToken(SQLAlchemyMCPTokenRepository(session)).execute(
            raw_token=raw_token,
        )
    except ExpiredMCPTokenError as exc:
        raise AIMCPHTTPError(401, "TOKEN_EXPIRED", "MCP token is expired.") from exc
    except RevokedMCPTokenError as exc:
        raise AIMCPHTTPError(401, "TOKEN_REVOKED", "MCP token is revoked.") from exc
    except InvalidMCPTokenError as exc:
        raise AIMCPHTTPError(401, "AUTH_INVALID", "Invalid MCP token.") from exc

    user = await session.get(UserRecord, token.user_id)
    if user is None or not user.is_verified or not user.is_active:
        raise AIMCPHTTPError(401, "AUTH_INVALID", "Invalid MCP token.")
    return MCPPrincipal(user=user, token=token)


MCPPrincipalDepends = Annotated[MCPPrincipal, Depends(get_mcp_principal)]
