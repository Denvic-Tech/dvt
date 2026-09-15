"""Shared security helpers for stable secret derivation."""

from __future__ import annotations

import base64
import hashlib
import hmac

_LEGACY_AUTH_DERIVATION_SALT = b"dvt-auth-secret-compat-v1"
_LEGACY_AUTH_DERIVATION_INFO_PREFIX = b"dvt/auth-secret/"


def derive_legacy_auth_secret(master_secret: str, secret_name: str) -> str:
    """Derive a stable 32-byte auth secret from a legacy installation secret.

    The implementation is HKDF-SHA256 (RFC 5869) for a single 32-byte output
    block. ``secret_name`` is part of HKDF ``info``, so every auth purpose gets
    a distinct value while all values remain stable across restarts/upgrades.
    """
    master_secret = master_secret.strip()
    secret_name = secret_name.strip()
    if not master_secret:
        raise ValueError("master_secret must not be empty")
    if not secret_name:
        raise ValueError("secret_name must not be empty")

    # HKDF-Extract(salt, IKM)
    prk = hmac.new(
        _LEGACY_AUTH_DERIVATION_SALT,
        master_secret.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    # HKDF-Expand(PRK, info, 32). SHA-256 output is exactly one required block.
    info = _LEGACY_AUTH_DERIVATION_INFO_PREFIX + secret_name.encode("utf-8")
    okm = hmac.new(prk, info + b"\x01", hashlib.sha256).digest()
    return base64.urlsafe_b64encode(okm).decode("ascii").rstrip("=")
