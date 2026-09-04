from collections.abc import Awaitable, Callable
from typing import Literal, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


# Значение или awaitable того же типа
MaybeAwaitable = R | Awaitable[R]


# Функция с произвольной сигнатурой P, возвращающая R или Awaitable[R]
MaybeAsyncFn = Callable[P, MaybeAwaitable[R]]


# Sentinel-тип для "значение не передано", аналог `undefined`.
# Используется для того, чтобы отличать явно переданый null.
# Literal значение `UNSET` находится в `src/constants.py`
UnsetType = Literal["__DVT_UNSET__"]
