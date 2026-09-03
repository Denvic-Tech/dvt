import re

_TOKEN_PATTERN = re.compile(r"dvt_mcp_[A-Za-z0-9-]+\.[A-Za-z0-9_-]+")
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*")
_URL_PASSWORD_PATTERN = re.compile(r"(?P<prefix>://[^:/@\s]+:)[^@/\s]+@")
_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|dsn)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_AWS_ACCESS_KEY_PATTERN = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")


def redact_log_message(message: str | None) -> str | None:
    if message is None:
        return None
    message = _TOKEN_PATTERN.sub("[REDACTED_MCP_TOKEN]", message)
    message = _BEARER_PATTERN.sub(r"\1[REDACTED]", message)
    message = _URL_PASSWORD_PATTERN.sub(r"\g<prefix>[REDACTED]@", message)
    message = _SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1\2[REDACTED]", message)
    return _AWS_ACCESS_KEY_PATTERN.sub("[REDACTED_ACCESS_KEY]", message)
