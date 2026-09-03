from __future__ import annotations

import hashlib
import hmac
import re
import time

from .entities import MCPToken
from .exceptions import ExpiredMCPTokenError, InvalidMCPTokenError, RevokedMCPTokenError
from .types import MCP_TOKEN_PREFIX

_TOKEN_PATTERN = re.compile(
    rf"^{re.escape(MCP_TOKEN_PREFIX)}(?P<token_id>[0-9a-fA-F-]{{36}})\.(?P<secret>[A-Za-z0-9_-]{{40,}})$"
)


def digest_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def parse_token_id(raw_token: str) -> str:
    match = _TOKEN_PATTERN.fullmatch(raw_token)
    if match is None:
        raise InvalidMCPTokenError("Invalid MCP token format.")
    return match.group("token_id")


def verify_token(token: MCPToken, raw_token: str, *, now_epoch: int | None = None) -> None:
    if token.is_deleted:
        raise RevokedMCPTokenError("MCP token is revoked.")
    now = int(time.time()) if now_epoch is None else now_epoch
    if token.expires_at is not None and token.expires_at <= now:
        raise ExpiredMCPTokenError("MCP token is expired.")
    if not hmac.compare_digest(token.token_digest, digest_token(raw_token)):
        raise InvalidMCPTokenError("Invalid MCP token.")
