from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pandas as pd
from pydantic import BaseModel


try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


JSON_ARRAY_ITEM_TOKEN = "[]"
JSON_ROOT_PATH = "/"
JSON_ROOT_DISPLAY_PATH = "$"


def _encode_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _decode_pointer_token(token: str) -> str:
    return token.replace("~1", "/").replace("~0", "~")


def json_safe(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, BaseModel):
        return json_safe(value.model_dump())

    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}

    if isinstance(value, set):
        return [json_safe(item) for item in sorted(value, key=lambda item: str(item))]

    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]

    if np is not None and isinstance(value, np.ndarray):
        return [json_safe(item) for item in value.tolist()]

    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    if isinstance(value, (str, int, bool)):
        return value

    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()

    if np is not None and isinstance(value, np.generic):
        return json_safe(value.item())

    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return float(value)

    return str(value)


def parse_json_path(path: str | None) -> tuple[str, ...]:
    if path is None:
        return ()

    raw_path = str(path).strip()
    if not raw_path or raw_path == JSON_ROOT_DISPLAY_PATH or raw_path == JSON_ROOT_PATH:
        return ()

    if raw_path.startswith(JSON_ROOT_DISPLAY_PATH):
        return _parse_display_path(raw_path)

    if raw_path.startswith(JSON_ROOT_PATH):
        return tuple(
            JSON_ARRAY_ITEM_TOKEN if part == JSON_ARRAY_ITEM_TOKEN else _decode_pointer_token(part)
            for part in raw_path.split("/")[1:]
            if part != ""
        )

    return _parse_display_path(raw_path, allow_root_prefix=False)


def _parse_display_path(path: str, *, allow_root_prefix: bool = True) -> tuple[str, ...]:
    raw_path = path.strip()
    if allow_root_prefix and raw_path.startswith(JSON_ROOT_DISPLAY_PATH):
        raw_path = raw_path[1:]
    raw_path = raw_path.lstrip(".")
    if not raw_path:
        return ()

    tokens: list[str] = []
    buffer: list[str] = []
    index = 0
    length = len(raw_path)

    while index < length:
        if raw_path.startswith(JSON_ARRAY_ITEM_TOKEN, index):
            if buffer:
                tokens.append("".join(buffer))
                buffer = []
            tokens.append(JSON_ARRAY_ITEM_TOKEN)
            index += len(JSON_ARRAY_ITEM_TOKEN)
            if index < length and raw_path[index] == ".":
                index += 1
            continue

        char = raw_path[index]
        if char == ".":
            if buffer:
                tokens.append("".join(buffer))
                buffer = []
            index += 1
            continue

        buffer.append(char)
        index += 1

    if buffer:
        tokens.append("".join(buffer))

    return tuple(token for token in tokens if token)


def build_machine_json_path(tokens: tuple[str, ...]) -> str:
    if not tokens:
        return JSON_ROOT_PATH
    return JSON_ROOT_PATH + "/".join(
        JSON_ARRAY_ITEM_TOKEN if token == JSON_ARRAY_ITEM_TOKEN else _encode_pointer_token(token)
        for token in tokens
    )


def build_display_json_path(tokens: tuple[str, ...]) -> str:
    if not tokens:
        return JSON_ROOT_DISPLAY_PATH

    parts = [JSON_ROOT_DISPLAY_PATH]
    for token in tokens:
        if token == JSON_ARRAY_ITEM_TOKEN:
            parts.append(JSON_ARRAY_ITEM_TOKEN)
        else:
            parts.append(f".{token}")
    return "".join(parts)


def normalize_json_path(path: str | None) -> str:
    return build_machine_json_path(parse_json_path(path))


def is_absolute_json_path(path: str | None) -> bool:
    if path is None:
        return False
    raw_path = str(path).strip()
    return raw_path.startswith(JSON_ROOT_DISPLAY_PATH) or raw_path.startswith(JSON_ROOT_PATH)


def join_json_path(base_tokens: tuple[str, ...], relative_tokens: tuple[str, ...]) -> tuple[str, ...]:
    if not relative_tokens:
        return base_tokens
    return base_tokens + relative_tokens


def is_json_path_prefix(prefix_tokens: tuple[str, ...], path_tokens: tuple[str, ...]) -> bool:
    if len(prefix_tokens) > len(path_tokens):
        return False
    return path_tokens[:len(prefix_tokens)] == prefix_tokens


def relative_json_path(
    path_tokens: tuple[str, ...],
    prefix_tokens: tuple[str, ...],
) -> tuple[str, ...] | None:
    if not is_json_path_prefix(prefix_tokens, path_tokens):
        return None
    return path_tokens[len(prefix_tokens):]


def tokens_to_output_key(tokens: tuple[str, ...], separator: str = ".") -> str:
    parts = [token for token in tokens if token != JSON_ARRAY_ITEM_TOKEN]
    if not parts:
        return "value"
    return separator.join(parts)


def resolve_json_path(data: Any, tokens: tuple[str, ...], *, missing: Any) -> Any:
    current = data
    for index, token in enumerate(tokens):
        if token == JSON_ARRAY_ITEM_TOKEN:
            if not isinstance(current, list):
                return missing
            rest = tokens[index + 1:]
            if not rest:
                return current
            return [
                resolve_json_path(item, rest, missing=missing)
                for item in current
            ]

        if not isinstance(current, dict) or token not in current:
            return missing

        current = current[token]

    return current
