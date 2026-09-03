import asyncio
import os
import sys
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any


class AsyncRunner:
    def __init__(self) -> None:
        # psycopg async connections require a selector-based loop on Windows.
        # Construct it explicitly so spawned Celery children do not depend on
        # process-global event loop policy timing.
        self._loop = (
            asyncio.SelectorEventLoop()
            if sys.platform.startswith("win")
            else asyncio.new_event_loop()
        )
        self._thread = threading.Thread(
            target=self._run_loop,
            name="task-worker-celery-loop",
            daemon=True,
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, Any]) -> Future[Any]:
        if not self.is_healthy():
            raise RuntimeError("AsyncRunner loop thread is not running")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return self.submit(coro).result()

    def stop(self) -> None:
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
        if not self._loop.is_closed():
            self._loop.close()

    def is_healthy(self) -> bool:
        return self._thread.is_alive() and not self._loop.is_closed()


_runner: AsyncRunner | None = None
_runner_pid: int | None = None
_runner_lock = threading.Lock()


def get_async_runner() -> AsyncRunner:
    global _runner, _runner_pid

    current_pid = os.getpid()
    with _runner_lock:
        pid_changed = _runner_pid is not None and _runner_pid != current_pid
        runner_is_healthy = _runner is not None and _runner.is_healthy()

        if _runner is None or pid_changed or not runner_is_healthy:
            # Only stop runner created in the same process.
            if _runner is not None and not pid_changed:
                _runner.stop()
            _runner = AsyncRunner()
            _runner_pid = current_pid

        return _runner
