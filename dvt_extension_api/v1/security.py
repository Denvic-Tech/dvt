"""Security capabilities backed by the DVT runtime configuration."""

from cryptography.fernet import Fernet

import config


class FernetKeyError(RuntimeError):
    """Raised when the effective DVT Fernet key is missing or invalid."""


def get_fernet_key() -> bytes:
    """Return the validated effective DVT Fernet key as URL-safe base64 bytes.

    Read the runtime configuration on each call. Do not read environment variables
    separately or generate a replacement key for persisted encrypted data.
    """
    raw_key = config.SECURITY.FERNET_KEY
    if not raw_key:
        raise FernetKeyError("DVT FERNET_KEY is not configured.")
    try:
        key = raw_key.encode("ascii") if isinstance(raw_key, str) else raw_key
        if not isinstance(key, bytes):
            raise TypeError
        Fernet(key)
    except (TypeError, ValueError):
        raise FernetKeyError("DVT FERNET_KEY is invalid.") from None
    return key


__all__ = ["FernetKeyError", "get_fernet_key"]
