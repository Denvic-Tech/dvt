from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable
from datetime import datetime
from urllib.parse import urlsplit

from .entities import AgentConnectCode, ConnectCodeStatus
from .exceptions import (
    ConnectCodeClaimLimitError,
    ConnectCodeExpiredError,
    ConnectCodeRevokedError,
    PublicUrlNotAllowedError,
)

# Letters and digits that are hard to confuse when read aloud or typed by hand.
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
CODE_LENGTH = 8


def generate_code() -> str:
    """Return a new public code such as ``K7F3-9QZX`` (40 bits of entropy)."""
    body = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    half = CODE_LENGTH // 2
    return f"{body[:half]}-{body[half:]}"


def normalize_code(raw_code: str) -> str:
    """Accept the code as typed: any case, with or without the dash."""
    cleaned = "".join(ch for ch in raw_code.strip().upper() if ch.isalnum())
    half = CODE_LENGTH // 2
    return f"{cleaned[:half]}-{cleaned[half:]}" if len(cleaned) == CODE_LENGTH else cleaned


def digest_code(raw_code: str) -> str:
    return hashlib.sha256(normalize_code(raw_code).encode("utf-8")).hexdigest()


def normalize_public_url(raw_url: str, allowed_origins: Iterable[str]) -> str:
    """Return ``scheme://host[:port]`` of the origin the UI reports, if it is a known DVT address.

    The agent instruction embeds absolute links, so the origin must come from a trusted list
    (the public addresses of this installation), never from a request header.
    """
    origin = _origin_of(raw_url)
    allowed = {_origin_of(item) for item in allowed_origins if item.strip()}
    if origin is None or origin not in allowed:
        raise PublicUrlNotAllowedError("base_url is not a public address of this DVT.")
    return origin


def _origin_of(raw_url: str) -> str | None:
    parts = urlsplit(raw_url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path not in {"", "/"}:
        return None
    if parts.query or parts.fragment or "@" in parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


def status_of(code: AgentConnectCode, now: datetime) -> ConnectCodeStatus:
    if code.is_revoked:
        return ConnectCodeStatus.REVOKED
    if code.claims_count > 0:
        return ConnectCodeStatus.CLAIMED
    if now >= code.expires_at:
        return ConnectCodeStatus.EXPIRED
    return ConnectCodeStatus.PENDING


def ensure_readable(code: AgentConnectCode, now: datetime) -> None:
    """The instruction may be read until the code expires, claimed or not."""
    if code.is_revoked:
        raise ConnectCodeRevokedError("Connection link was revoked.")
    if now >= code.expires_at:
        raise ConnectCodeExpiredError("Connection link has expired.")


def ensure_claimable(code: AgentConnectCode, now: datetime, *, max_claims: int) -> None:
    ensure_readable(code, now)
    if code.claims_count >= max_claims:
        raise ConnectCodeClaimLimitError("Connection link was used too many times.")
