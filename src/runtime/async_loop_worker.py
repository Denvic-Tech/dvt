import asyncio
import threading
import traceback
from concurrent.futures import Future as ConcurrentFuture
from typing import Optional, Awaitable, Any


class AsyncLoopWorker:
    """
    Один event loop в отдельном треде на весь процесс.
    Позволяет синхронному коду выполнять async-корутины: run(coro).
    """

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._started = threading.Event()
        self._owns_loop = False
        self._state_lock = threading.RLock()

    @property
    def loop(self) -> Optional[asyncio.AbstractEventLoop]:
        return self._loop

    @property
    def owns_loop(self) -> bool:
        return self._owns_loop

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Привязывает воркер к уже существующему event loop без создания отдельного треда.
        """
        with self._state_lock:
            if self._loop is loop:
                return
            should_stop_own_loop = self._loop is not None and self._owns_loop

        if should_stop_own_loop:
            self.stop()

        with self._state_lock:
            self._loop = loop
            self._thread = None
            self._owns_loop = False
            self._started.set()

    def ensure_own_loop(self) -> asyncio.AbstractEventLoop:
        """
        Гарантирует, что воркер использует собственный event loop в отдельном потоке.
        Если был привязан к внешнему loop, отвязывает его и запускает новый.
        """
        with self._state_lock:
            if self._owns_loop and self._loop is not None and not self._loop.is_closed():
                if self._thread is not None and self._thread.is_alive():
                    return self._loop
                # Состояние рассинхронизировано: loop есть, но поток уже умер.
                self._loop = None
                self._thread = None
                self._owns_loop = False
                self._started.clear()

            if self._loop is not None and not self._owns_loop:
                self._loop = None
                self._thread = None
                self._started.clear()

        self.start()
        with self._state_lock:
            loop = self._loop
        if loop is None:
            raise RuntimeError("Failed to start AsyncLoopWorker loop.")
        return loop

    def start(self) -> None:
        should_wait = False
        with self._state_lock:
            if self._loop is not None and not self._loop.is_closed():
                if not self._owns_loop:
                    return
                if self._thread is not None and self._thread.is_alive():
                    return
                # Есть loop, но нет живого рабочего потока — перезапускаем состояние.
                self._loop = None
                self._thread = None
                self._owns_loop = False
                self._started.clear()

            if self._thread is not None and self._thread.is_alive():
                should_wait = True
            else:
                self._loop = None
                self._thread = None
                self._started.clear()
                self._owns_loop = True

                def _runner():
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    self._loop = loop
                    self._started.set()
                    try:
                        loop.run_forever()
                    except Exception:
                        # Поток event loop не должен падать бесшумно:
                        # keep traceback in stderr for diagnostics.
                        traceback.print_exc()
                    finally:
                        pending = asyncio.all_tasks(loop=loop)
                        for task in pending:
                            task.cancel()
                        try:
                            if pending:
                                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                        finally:
                            loop.close()
                            with self._state_lock:
                                if self._loop is loop:
                                    self._loop = None
                                if self._thread is threading.current_thread():
                                    self._thread = None
                                self._owns_loop = False
                                self._started.clear()

                thread = threading.Thread(target=_runner, name="AsyncLoopWorker", daemon=True)
                self._thread = thread
                thread.start()
                should_wait = True

        if should_wait:
            self._started.wait()

    def submit(self, coro: Awaitable[Any]) -> ConcurrentFuture:
        """
        Планирует выполнение coroutine на рабочем event loop и возвращает concurrent future.
        """
        loop: asyncio.AbstractEventLoop | None = self.ensure_own_loop()
        if not self._started.is_set():
            self._started.wait()
        with self._state_lock:
            if loop.is_closed() or (
                    self._owns_loop and (self._thread is None or not self._thread.is_alive())
            ):
                loop = None
        if loop is None:
            loop = self.ensure_own_loop()
        return asyncio.run_coroutine_threadsafe(coro, loop)  # type: ignore[arg-type]

    async def run_async(self, coro: Awaitable[Any]) -> Any:
        """
        Асинхронно ожидает завершения coroutine, запущенной на рабочем event loop.
        """
        fut = self.submit(coro)
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            # Нет активного event loop (синхронный контекст)
            return fut.result()
        return await asyncio.wrap_future(fut, loop=current_loop)

    def stop(self, timeout: float = 2.0) -> None:
        with self._state_lock:
            loop = self._loop
            thread = self._thread
            owns_loop = self._owns_loop

        if not loop:
            return

        if owns_loop:
            try:
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:
                pass
            if thread:
                thread.join(timeout=timeout)

        with self._state_lock:
            if self._loop is loop:
                self._loop = None
            if self._thread is thread:
                self._thread = None
            self._owns_loop = False
            self._started.clear()

    def run(self, coro: Awaitable[Any]) -> Any:
        """
        Выполняет корутину в фоновом loop и блокирующе ждёт результат.
        Можно вызывать из любых потоков (в т.ч. из dask map_partitions).
        """
        future = self.submit(coro)
        return future.result()
