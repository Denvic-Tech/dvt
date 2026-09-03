import asyncio
import threading

from src.runtime.async_loop_worker import AsyncLoopWorker


def test_async_loop_worker_starts_single_thread_under_concurrency() -> None:
    worker = AsyncLoopWorker()
    before = {thread.ident for thread in threading.enumerate() if thread.name == "AsyncLoopWorker"}

    barrier = threading.Barrier(32)
    result_loop_ids: list[int] = []
    errors: list[Exception] = []
    result_lock = threading.Lock()

    def _target() -> None:
        try:
            barrier.wait(timeout=5)
            loop = worker.ensure_own_loop()
            with result_lock:
                result_loop_ids.append(id(loop))
        except Exception as exc:  # pragma: no cover - guard for thread failures
            with result_lock:
                errors.append(exc)

    threads = [threading.Thread(target=_target, daemon=True) for _ in range(32)]

    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)

        assert all(not thread.is_alive() for thread in threads)
        assert not errors
        assert len(result_loop_ids) == 32
        assert len(set(result_loop_ids)) == 1
    finally:
        worker.stop(timeout=5)

    after = {thread.ident for thread in threading.enumerate() if thread.name == "AsyncLoopWorker"}
    new_async_threads = {ident for ident in (after - before) if ident is not None}
    assert len(new_async_threads) <= 1


def test_async_loop_worker_restarts_after_unexpected_loop_stop() -> None:
    worker = AsyncLoopWorker()
    first_loop = worker.ensure_own_loop()
    first_thread = worker._thread

    assert first_thread is not None
    first_loop.call_soon_threadsafe(first_loop.stop)
    first_thread.join(timeout=5)
    assert not first_thread.is_alive()

    result = worker.run(asyncio.sleep(0, result="ok"))
    second_loop = worker.loop
    second_thread = worker._thread

    try:
        assert result == "ok"
        assert second_loop is not None
        assert second_loop is not first_loop
        assert second_thread is not None
        assert second_thread is not first_thread
        assert second_thread.is_alive()
    finally:
        worker.stop(timeout=5)
