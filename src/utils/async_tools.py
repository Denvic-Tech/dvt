import asyncio
import inspect
from typing import Optional, Callable, TypeVar, Awaitable, ParamSpec, Protocol, Generic, overload, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class SyncQueueProtocol(Protocol[T]):
    def get(self, block: bool = True, timeout: Optional[float] = None) -> T: ...
    def put(self, item: T, block: bool = True, timeout: Optional[float] = None) -> None: ...

    def get_nowait(self) -> T: ...
    def put_nowait(self, item: T) -> None: ...


class AsyncQueue(Generic[T]):
    def __init__(self, queue: SyncQueueProtocol[T]):
        self._queue = queue

    async def get(self, block: bool = True, timeout: Optional[float] = None) -> T:
        return await asyncio.to_thread(self._queue.get, block, timeout)

    async def put(self, item: T, block: bool = True, timeout: Optional[float] = None) -> None:
        await asyncio.to_thread(self._queue.put, item, block, timeout)

    async def get_nowait(self) -> T:
        return await asyncio.to_thread(self._queue.get_nowait)

    async def put_nowait(self, item: T) -> None:
        await asyncio.to_thread(self._queue.put_nowait, item)


P = ParamSpec("P")
R = TypeVar("R")


@overload
async def run_callable(
        fn: Callable[P, Awaitable[R]],
        /,
        *args: P.args,
        offload_sync: bool = True,
        **kwargs: P.kwargs,
) -> R: ...


@overload
async def run_callable(
        fn: Callable[P, R],
        /,
        *args: P.args,
        offload_sync: bool = True,
        **kwargs: P.kwargs,
) -> R: ...


async def run_callable(
        fn: Callable[P, Awaitable[R]] | Callable[P, R],
        /,
        *args: P.args,
        offload_sync: bool = True,
        **kwargs: P.kwargs,
) -> R:
    """
    Универсальный раннер для sync/async callable.

    - Если `fn` — async def или вернул awaitable: await.
    - Если `fn` — sync:
        * при `offload_sync=True` выполнит в отдельном потоке через asyncio.to_thread(),
          чтобы не блокировать event loop;
        * при `offload_sync=False` вызовет прямо в текущем потоке.

    Возвращает R (вызовите как `await run_callable(...)`).
    """
    # Явная coroutine-function: просто await вызова
    if inspect.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)  # type: ignore[misc]

    if offload_sync:
        return await asyncio.to_thread(fn, *args, **kwargs)  # type: ignore[misc]

    # Прямой вызов синхронной функции (или callable-объекта)
    res = fn(*args, **kwargs)
    if inspect.isawaitable(res):  # на случай, если вернули coroutine/awaitable
        return await res  # type: ignore[no-any-return]

    return res  # type: ignore[return-value]
