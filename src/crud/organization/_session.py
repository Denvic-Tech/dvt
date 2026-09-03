from __future__ import annotations

from inspect import isawaitable
from typing import TypeVar

T = TypeVar("T")


async def maybe_await(value: T) -> T:
    if isawaitable(value):
        return await value
    return value

