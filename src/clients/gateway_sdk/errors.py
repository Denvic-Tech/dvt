from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class DVTError(Exception):
    """Base SDK exception."""


class DVTTransportError(DVTError):
    """Network or transport-layer failure."""

    def __init__(self, message: str, *, cause: Exception | None = None):
        super().__init__(message)
        self.cause = cause


class DVTAPIError(DVTError):
    """HTTP error returned by Gateway."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        method: str,
        path: str,
        response_text: str | None = None,
        response_json: Mapping[str, Any] | list[Any] | None = None,
        hint: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.method = method
        self.path = path
        self.response_text = response_text
        self.response_json = response_json
        self.hint = hint

    def __str__(self) -> str:
        base = f"{self.method.upper()} {self.path} failed with HTTP {self.status_code}"
        if self.hint:
            return f"{base}. {self.hint}"
        return base


class DVTValidationError(DVTAPIError):
    """Validation failure reported by Gateway."""


class DVTAuthError(DVTAPIError):
    """Authentication or authorization failure."""
