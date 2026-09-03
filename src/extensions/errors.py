from __future__ import annotations

import re

_NAMED_SECRET_RE = re.compile(
    r"(?i)(password|passwd|secret|token|api[_-]?key|authorization)(\s*[=:]\s*)([^\s,;]+)"
)
_QUOTED_NAMED_SECRET_RE = re.compile(
    r'''(?i)((?:["']?)(?:password|passwd|secret|token|api[_-]?key|authorization)(?:["']?)\s*[=:]\s*)(["'])(.*?)(\2)'''
)
_AUTHORIZATION_RE = re.compile(
    r'''(?i)((?:["']?)authorization(?:["']?)\s*[=:]\s*)([^,;\r\n}]+)'''
)
_URL_CREDENTIAL_RE = re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^:/\s]+:)[^@\s]+@")


def sanitize_extension_error(message: object, *, limit: int = 2000) -> str:
    value = str(message).replace("\r", " ").replace("\n", " ").strip()
    value = _URL_CREDENTIAL_RE.sub(r"\1***@", value)
    value = _QUOTED_NAMED_SECRET_RE.sub(r"\1\2***\2", value)
    value = _AUTHORIZATION_RE.sub(r"\1***", value)
    value = _NAMED_SECRET_RE.sub(r"\1\2***", value)
    if len(value) > limit:
        value = f"{value[: limit - 3]}..."
    return value


def stage_error(stage: str, message: object) -> str:
    return f"{stage}: {sanitize_extension_error(message)}"


__all__ = ["sanitize_extension_error", "stage_error"]
