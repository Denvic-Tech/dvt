from __future__ import annotations

import re


_ERROR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"timeout|timed out", re.IGNORECASE), "timeout"),
    (re.compile(r"permission|forbidden|unauthorized|access denied", re.IGNORECASE), "permission"),
    (re.compile(r"connection|network|refused|unavailable|broken pipe", re.IGNORECASE), "connection"),
    (re.compile(r"validation|invalid|schema", re.IGNORECASE), "validation"),
    (re.compile(r"memory|out of memory", re.IGNORECASE), "memory"),
    (re.compile(r"syntax|sql", re.IGNORECASE), "sql"),
    (re.compile(r"cancel", re.IGNORECASE), "cancelled"),
)


def normalize_error_category(message: str | None) -> str:
    if not message:
        return "unknown_error"

    for pattern, category in _ERROR_PATTERNS:
        if pattern.search(message):
            return category

    return "unknown_error"
