import base64

from .errors import AIMCPHTTPError


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii") + b"===").decode("ascii")
        value = int(raw)
    except (ValueError, UnicodeError) as exc:
        raise AIMCPHTTPError(422, "GRAPH_VALIDATION_FAILED", "Invalid pagination cursor.") from exc
    if value < 0:
        raise AIMCPHTTPError(422, "GRAPH_VALIDATION_FAILED", "Invalid pagination cursor.")
    return value


def encode_cursor(offset: int, total: int) -> str | None:
    if offset >= total:
        return None
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii").rstrip("=")
