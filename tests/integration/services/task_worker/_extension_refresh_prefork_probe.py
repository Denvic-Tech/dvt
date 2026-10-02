"""Standalone subprocess for deterministic real-prefork regression tests."""
from __future__ import annotations

import os
import select
import signal
import sys
import time
from concurrent.futures import Future
from functools import partial
from types import SimpleNamespace

import billiard
from celery import Celery, signals
from celery.apps.worker import install_worker_term_handler
from celery.concurrency import prefork
from celery.concurrency.asynpool import Worker
from celery.concurrency.prefork import TaskPool
from celery.worker.consumer.consumer import Consumer
from kombu import Exchange, Queue
from kombu.asynchronous import Hub

from services.task_worker.extension_refresh import ExtensionRuntimeRefresh, consumer_is_ready

MODE = sys.argv[1] if len(sys.argv) > 1 else "fork"
DELAY_NEXT_CHILD = False
barrier_read, barrier_write = os.pipe()
release_read, release_write = os.pipe()
term_read, term_write = os.pipe()


def wait_at_barrier():
    os.write(barrier_write, b"ready")
    os.read(release_read, 1)


def after_fork():
    if MODE == "fork" and DELAY_NEXT_CHILD:
        wait_at_barrier()


def inherited_term_seen(**_kwargs):
    os.write(term_write, b"term")


def fail(reason):
    raise SystemExit(reason)


os.register_at_fork(after_in_child=after_fork)
signals.worker_shutting_down.connect(inherited_term_seen, weak=False)
install_worker_term_handler(SimpleNamespace(hostname="prefork-regression"))
original_initializer = prefork.process_initializer
original_loop_start = Worker.on_loop_start


def initializer(app, hostname):
    if MODE == "bootstrap" and DELAY_NEXT_CHILD:
        handler = signal.getsignal(signal.SIGTERM)

        def inherited_after_bootstrap(signum, frame):
            handler(signum, frame)
            os.write(term_write, b"term")

        signal.signal(signal.SIGTERM, inherited_after_bootstrap)
        wait_at_barrier()
    original_initializer(app, hostname)


def on_loop_start(self, pid):
    if MODE == "ignore-term" and DELAY_NEXT_CHILD:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    original_loop_start(self, pid)


prefork.process_initializer = initializer
Worker.on_loop_start = on_loop_start


def pump(hub, duration=0.05):
    deadline = time.monotonic() + duration
    hub.call_later(duration, lambda: None)
    while time.monotonic() < deadline:
        hub.run_once()


def until(hub, condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        pump(hub)
    assert condition(), "prefork condition timed out"


def main():
    global DELAY_NEXT_CHILD  # noqa: PLW0603
    names = ("tasks.worker", "tasks.deps")
    hub = Hub()
    with Celery("refresh-regression", broker="memory://", set_as_current=False) as app:
        app.conf.task_queues = [Queue(n, Exchange(n), routing_key=n) for n in names]
        pool = TaskPool(1, app=app, threads=False, maxtasksperchild=1,
                        initargs=(app, "prefork-regression"))
        try:
            pool.start()
            raw = pool._pool
            pool.register_with_event_loop(hub)
            with app.connection_for_read() as connection:
                consumer = SimpleNamespace(
                    app=app, pool=pool, connection=connection, timer=hub.timer,
                    task_consumer=app.amqp.TaskConsumer(connection),
                )
                consumer.cancel_task_queue = partial(Consumer.cancel_task_queue, consumer)
                consumer.add_task_queue = partial(Consumer.add_task_queue, consumer)
                consumer.task_consumer.consume()
                until(hub, lambda: bool(raw._fileno_to_inq))
                first_pid = raw._pool[0].pid
                results = []
                DELAY_NEXT_CHILD = True
                raw.apply_async(os.getpid, callback=results.append)
                until(hub, lambda: results == [first_pid] and bool(raw._pool)
                      and raw._pool[0].pid != first_pid)
                if MODE != "ignore-term":
                    assert select.select([barrier_read], [], [], 2)[0]
                    os.read(barrier_read, 5)
                else:
                    until(hub, lambda: bool(raw._fileno_to_inq))
                retiring_pid = raw._pool[0].pid
                reloads = []

                def submit_reload():
                    assert raw._processes == 0 and raw._pool == []
                    reloads.append(True)
                    result = Future()
                    result.set_result(True)
                    return result

                refresh = ExtensionRuntimeRefresh(
                    consumer, names, submit_reload=submit_reload,
                    on_refreshed=lambda: None, on_failure=fail,
                )
                refresh.EXIT_TIMEOUT_SEC = 0.5
                refresh.KILL_TIMEOUT_SEC = 3
                assert refresh.request()
                assert not refresh.request()
                pump(hub, 0.25)
                assert consumer.task_consumer.queues == []
                if MODE != "ignore-term":
                    assert raw._processes == 1, "shrink ran before WORKER_UP"
                    assert not select.select([term_read], [], [], 0)[0], "early SIGTERM"
                    assert reloads == []
                    DELAY_NEXT_CHILD = False
                    os.write(release_write, b"x")
                else:
                    DELAY_NEXT_CHILD = False
                    assert raw._processes == 0
                    assert raw._pool[0].is_alive(), "test child did not ignore SIGTERM"
                until(hub, lambda: not refresh.in_progress)
                assert reloads == [True]
                assert consumer_is_ready(consumer, names, prefork=True)
                assert raw._processes == 1
                assert len(raw._pool) == 1 and raw._pool[0].pid != retiring_pid
                assert set(app.amqp.queues.consume_from) == set(names)

                followup = []
                raw.apply_async(os.getpid, callback=followup.append)
                until(hub, lambda: bool(followup))
                assert len(followup) == 1
                assert not select.select([term_read], [], [], 0)[0]
                print(
                    f"PASS mode={MODE} billiard={billiard.__version__}: "
                    "queues restored, next job executed"
                )
                consumer.task_consumer.cancel()
        finally:
            if pool._pool is not None:
                for child in tuple(pool._pool._pool):
                    if child.is_alive():
                        os.kill(child.pid, signal.SIGKILL)
                pool.terminate()
            hub.close()
            for fd in (barrier_read, barrier_write, release_read, release_write, term_read, term_write):
                os.close(fd)


if __name__ == "__main__":
    main()
