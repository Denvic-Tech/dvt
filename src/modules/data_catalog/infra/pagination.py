import base64


def decode_offset_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii") + b"===").decode("ascii")
        value = int(raw)
    except (ValueError, UnicodeError):
        return 0
    return max(value, 0)


def encode_offset_cursor(offset: int, total: int) -> str | None:
    if offset >= total:
        return None
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii").rstrip("=")
