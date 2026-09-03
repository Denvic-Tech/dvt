from __future__ import annotations

from collections.abc import Iterable


def resolve_ttl(ttl_lifetime: int | None, default_ttl: int) -> int:
    if default_ttl <= 0:
        raise ValueError("default_ttl must be greater than zero")
    if ttl_lifetime is None or ttl_lifetime <= 0:
        return default_ttl
    return ttl_lifetime


def dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
