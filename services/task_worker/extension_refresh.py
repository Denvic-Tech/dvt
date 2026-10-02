"""Drain and refresh a one-slot Celery prefork worker without racing child startup."""
from __future__ import annotations

import os
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import NoReturn

from billiard.pool import SIGKILL


def ready_pool_children(raw_pool) -> tuple:
    # AsynPool installs this index only after receiving WORKER_UP, after the
    # child's signal handlers have replaced the inherited MainProcess handlers.
    ready = tuple(getattr(raw_pool, "_fileno_to_inq", {}).values())
    return tuple(
        child for child in tuple(raw_pool._pool)
        if child.is_alive() and any(child is item for item in ready)
    )


def resume_task_queues(consumer, queue_names: tuple[str, ...]) -> None:
    queues = consumer.app.amqp.queues
    for name in queue_names:
        # cancel_task_queue also deselects the queues used after reconnect.
        queues.select_add(queues[name])
        consumer.add_task_queue(name)


def consumer_is_ready(consumer, queue_names: tuple[str, ...], *, prefork: bool) -> bool:
    if consumer is None:
        return False
    try:
        if not consumer.connection or not consumer.connection.connected:
            return False
        if not consumer.task_consumer or not all(
            consumer.task_consumer.consuming_from(name) for name in queue_names
        ):
            return False
        if prefork:
            raw = consumer.pool._pool
            return (
                raw._processes == 1
                and len(raw._pool) == 1
                and len(ready_pool_children(raw)) == 1
            )
    except (AttributeError, OSError, RuntimeError):
        # Heartbeats run on the async thread while Celery replaces consumers.
        return False
    else:
        return True


def exit_unusable_idle_worker(reason: str) -> NoReturn:
    # Only called after the pool's active request cache is empty. A cancelled
    # extension import can still be mutating the registry on the async thread:
    # never fork from that state or wait for that thread during graceful exit.
    # Production Compose restarts this container with restart: unless-stopped.
    try:
        os.write(2, f"DVT idle worker cannot finish extension refresh: {reason}\n".encode())
    finally:
        os._exit(70)


class ExtensionRuntimeRefresh:
    POLL_SEC = 0.1
    READY_TIMEOUT_SEC = 30.0
    EXIT_TIMEOUT_SEC = 10.0
    KILL_TIMEOUT_SEC = 5.0
    RELOAD_TIMEOUT_SEC = 60.0

    def __init__(
        self,
        consumer,
        queue_names: tuple[str, ...],
        *,
        submit_reload: Callable[[], Future],
        on_refreshed: Callable[[], None],
        on_failure: Callable[[str], NoReturn] = exit_unusable_idle_worker,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.consumer = consumer
        self.queue_names = queue_names
        self.submit_reload = submit_reload
        self.on_refreshed = on_refreshed
        self.on_failure = on_failure
        self.clock = clock
        self.phase = "idle"
        self.deadline: float | None = None
        self.failure: str | None = None
        self._raw_pool = None
        self._reload: Future | None = None
        self._retiring_children: tuple = ()

    @property
    def in_progress(self) -> bool:
        return self.phase != "idle"

    def request(self) -> bool:
        if self.in_progress:
            return False
        self._raw_pool = self.consumer.pool._pool
        self.failure = None
        self._set_phase("draining")
        try:
            for name in self.queue_names:
                self.consumer.cancel_task_queue(name)
        except Exception as exc:
            # A task may still be running. Defer failure until it finishes.
            self.failure = f"pausing queues: {type(exc).__name__}"
            self._set_phase("failed")
        self._schedule()
        return True

    def _set_phase(self, phase: str, timeout: float | None = None) -> None:
        self.phase = phase
        self.deadline = None if timeout is None else self.clock() + timeout

    def _schedule(self) -> None:
        self.consumer.timer.call_after(self.POLL_SEC, self.tick, ())

    def _expired(self) -> bool:
        return self.deadline is not None and self.clock() >= self.deadline

    def _fail(self, reason: str) -> None:
        self.failure = reason
        self._set_phase("failed")
        if self._reload is not None:
            self._reload.cancel()
        if not self.consumer.pool._pool._cache:
            self.on_failure(reason)

    def tick(self) -> None:
        if not self.in_progress:
            return
        try:
            self._advance()
        except Exception as exc:
            self._fail(f"{self.phase}: {type(exc).__name__}")
        if self.in_progress:
            self._schedule()

    def _advance(self) -> None:
        raw = self.consumer.pool._pool
        if raw is not self._raw_pool:
            self._fail("pool replaced during refresh")
            return

        if raw._cache:
            # Pipeline duration is unrestricted. No refresh deadline may kill
            # an executing request, including one still in its result/ack path.
            if self.deadline is not None:
                self.deadline = self.clock() + (
                    self.KILL_TIMEOUT_SEC if self.phase == "killing"
                    else self.EXIT_TIMEOUT_SEC if self.phase == "stopping"
                    else self.READY_TIMEOUT_SEC
                )
            return
        if self.phase == "failed":
            self.on_failure(self.failure or "refresh failed")
            return

        if self.phase == "draining":
            self._set_phase("waiting_for_child", self.READY_TIMEOUT_SEC)

        advance = {
            "waiting_for_child": self._wait_for_child,
            "stopping": self._stop_child,
            "killing": self._stop_child,
            "reloading": self._reload_runtime,
            "starting": self._start_child,
        }[self.phase]
        advance(raw)

    def _wait_for_child(self, raw) -> None:
        if raw._processes != 1:
            self._fail("unexpected pool size before shrink")
            return
        children = tuple(raw._pool)
        if len(children) != 1 or ready_pool_children(raw) != children:
            if self._expired():
                self._fail("child did not become ready before shrink")
            return
        try:
            self.consumer.pool.shrink(1)
        except ValueError:
            if self._expired():
                self._fail("idle pool could not shrink")
            return
        self._retiring_children = children
        # Keep QoS unchanged: final concurrency remains 1. Celery skips a
        # decrement at size 0, so decrement/grow pairs accumulate prefetch.
        self._set_phase("stopping", self.EXIT_TIMEOUT_SEC)
        return

    def _stop_child(self, raw) -> None:
        if raw._processes != 0:
            self._fail("pool grew before runtime reload")
            return
        if raw._pool:
            if not self._expired():
                return
            if self.phase == "killing":
                self._fail("idle child did not exit after SIGKILL")
                return
            children = tuple(raw._pool)
            if any(child not in self._retiring_children for child in children):
                self._fail("unexpected replacement child while draining")
                return
            # No request remains and no task queues are subscribed. Only
            # the children already selected by shrink may be terminated.
            for child in children:
                if child.is_alive():
                    raw.terminate_job(child.pid, SIGKILL)
            self._set_phase("killing", self.KILL_TIMEOUT_SEC)
            return
        self._reload = self.submit_reload()
        self._set_phase("reloading", self.RELOAD_TIMEOUT_SEC)
        return

    def _reload_runtime(self, raw) -> None:
        if not self._reload.done():
            if self._expired():
                self._fail("extension runtime reload timed out")
            return
        changed = self._reload.result()
        if changed:
            self.on_refreshed()
        self._reload = None
        if raw._processes != 0:
            self._fail("unexpected pool size after reload")
            return
        self.consumer.pool.grow(1)
        self._set_phase("starting", self.READY_TIMEOUT_SEC)
        return

    def _start_child(self, raw) -> None:
        if (
            raw._processes != 1
            or len(raw._pool) != 1
            or len(ready_pool_children(raw)) != 1
        ):
            if self._expired():
                self._fail("replacement child did not become ready")
            return
        resume_task_queues(self.consumer, self.queue_names)
        self._retiring_children = ()
        self._set_phase("idle")

    def snapshot(self) -> dict:
        return {
            "phase": self.phase,
            "failure": self.failure,
            **pool_snapshot(self.consumer.pool._pool),
        }


def pool_snapshot(raw) -> dict:
    ready = ready_pool_children(raw)
    return {
        "pool_target_size": raw._processes,
        "pool_request_count": len(raw._cache),
        "children": [
            {
                "pid": child.pid,
                "alive": child.is_alive(),
                "ready": child in ready,
                "controlled_termination": bool(
                    getattr(child, "_controlled_termination", False)
                ),
            }
            for child in tuple(raw._pool)
        ],
    }
