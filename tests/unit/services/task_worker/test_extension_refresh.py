from concurrent.futures import Future
from functools import partial
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from billiard.pool import SIGKILL
from celery import Celery
from celery.worker.consumer.consumer import Consumer
from kombu import Exchange, Queue

from services.task_worker.extension_refresh import ExtensionRuntimeRefresh, consumer_is_ready


class FatalIdleWorker(BaseException):
    pass


class Child:
    def __init__(self, pid):
        self.pid = pid
        self.alive = True

    def is_alive(self):
        return self.alive


@pytest.fixture
def runtime():
    names = ("tasks.worker", "tasks.deps")
    now = [0.0]
    events = []
    child = Child(10)
    raw = SimpleNamespace(
        _cache={}, _pool=[child], _processes=1, _fileno_to_inq={},
        terminate_job=Mock(),
    )

    def shrink(count):
        events.append("shrink")
        raw._processes -= count

    def grow(count):
        events.append("grow")
        raw._processes += count
        raw._pool = [Child(11)]

    def fail(reason):
        raise FatalIdleWorker(reason)

    future = Future()
    submit = Mock(return_value=future)
    with Celery("refresh", broker="memory://", set_as_current=False) as app:
        app.conf.task_queues = [
            Queue(name, exchange=Exchange(name), routing_key=name) for name in names
        ]
        with app.connection_for_read() as connection:
            consumer = SimpleNamespace(
                app=app, connection=connection,
                pool=SimpleNamespace(_pool=raw, shrink=shrink, grow=grow),
                timer=SimpleNamespace(call_after=Mock()),
                task_consumer=app.amqp.TaskConsumer(connection),
                _update_prefetch_count=Mock(side_effect=AssertionError("QoS must stay unchanged")),
            )
            consumer.cancel_task_queue = partial(Consumer.cancel_task_queue, consumer)
            consumer.add_task_queue = partial(Consumer.add_task_queue, consumer)
            consumer.task_consumer.consume()
            refresh = ExtensionRuntimeRefresh(
                consumer, names, submit_reload=submit, on_refreshed=Mock(),
                on_failure=fail, clock=lambda: now[0],
            )
            yield SimpleNamespace(
                refresh=refresh, raw=raw, child=child, names=names, now=now,
                events=events, future=future, submit=submit, consumer=consumer,
            )
            consumer.task_consumer.cancel()


def make_ready(runtime):
    runtime.raw._fileno_to_inq = {1: runtime.raw._pool[0]}


def finish_drain(runtime):
    runtime.raw._pool = []
    runtime.raw._fileno_to_inq = {}
    runtime.refresh.tick()


def start_reload(runtime):
    make_ready(runtime)
    runtime.refresh.request()
    runtime.refresh.tick()
    finish_drain(runtime)


def test_waits_for_worker_up_before_sending_term(runtime):
    assert runtime.refresh.request()
    assert not runtime.refresh.request()
    runtime.refresh.tick()

    assert runtime.events == []
    assert runtime.submit.call_count == 0
    assert runtime.consumer.task_consumer.queues == []
    assert not consumer_is_ready(runtime.consumer, runtime.names, prefork=True)

    make_ready(runtime)
    runtime.refresh.tick()
    assert runtime.events == ["shrink"]


def test_active_task_and_result_ack_path_have_no_refresh_deadline(runtime):
    runtime.raw._cache["request"] = object()
    runtime.refresh.request()
    runtime.now[0] = 100_000
    runtime.refresh.tick()
    assert runtime.events == []
    runtime.raw.terminate_job.assert_not_called()

    runtime.raw._cache.clear()
    make_ready(runtime)
    runtime.refresh.tick()
    assert runtime.events == ["shrink"]


def test_restores_queues_only_after_reload_and_replacement_worker_up(runtime):
    start_reload(runtime)
    assert runtime.submit.call_count == 1
    runtime.refresh.tick()
    assert runtime.events == ["shrink"]
    assert runtime.consumer.task_consumer.queues == []

    runtime.future.set_result(True)
    runtime.refresh.tick()
    assert runtime.events == ["shrink", "grow"]
    assert runtime.consumer.task_consumer.queues == []
    assert runtime.refresh.in_progress
    runtime.consumer._update_prefetch_count.assert_not_called()

    make_ready(runtime)
    runtime.refresh.tick()
    assert not runtime.refresh.in_progress
    assert consumer_is_ready(runtime.consumer, runtime.names, prefork=True)
    with runtime.consumer.app.amqp.TaskConsumer(runtime.consumer.connection) as recreated:
        assert {q.name for q in recreated.queues} == set(runtime.names)


def test_waits_for_child_reaping_before_import(runtime):
    make_ready(runtime)
    runtime.refresh.request()
    runtime.refresh.tick()
    runtime.child.alive = False
    runtime.refresh.tick()
    runtime.submit.assert_not_called()
    finish_drain(runtime)
    runtime.submit.assert_called_once()


def test_stuck_idle_child_gets_bounded_kill_then_recovers(runtime):
    make_ready(runtime)
    runtime.refresh.request()
    runtime.refresh.tick()
    runtime.now[0] += runtime.refresh.EXIT_TIMEOUT_SEC
    runtime.refresh.tick()
    runtime.raw.terminate_job.assert_called_once_with(10, SIGKILL)
    runtime.submit.assert_not_called()

    finish_drain(runtime)
    runtime.future.set_result(False)
    runtime.refresh.tick()
    make_ready(runtime)
    runtime.refresh.tick()
    assert consumer_is_ready(runtime.consumer, runtime.names, prefork=True)


def test_never_kills_a_request_that_appears_during_drain(runtime):
    make_ready(runtime)
    runtime.refresh.request()
    runtime.refresh.tick()
    runtime.raw._cache["late-result"] = object()
    runtime.now[0] = 100_000
    runtime.refresh.tick()
    runtime.raw.terminate_job.assert_not_called()
    runtime.raw._cache.clear()
    runtime.refresh.tick()
    runtime.raw.terminate_job.assert_not_called()


def test_unreapable_idle_child_exits_worker_instead_of_waiting_forever(runtime):
    make_ready(runtime)
    runtime.refresh.request()
    runtime.refresh.tick()
    runtime.now[0] += runtime.refresh.EXIT_TIMEOUT_SEC
    runtime.refresh.tick()
    runtime.now[0] += runtime.refresh.KILL_TIMEOUT_SEC
    with pytest.raises(FatalIdleWorker, match="SIGKILL"):
        runtime.refresh.tick()
    assert runtime.events == ["shrink"]


@pytest.mark.parametrize("replacement", [False, True])
def test_child_startup_timeout_exits_idle_worker(runtime, replacement):
    if replacement:
        start_reload(runtime)
        runtime.future.set_result(False)
        runtime.refresh.tick()
    else:
        runtime.refresh.request()
        runtime.refresh.tick()
    runtime.now[0] += runtime.refresh.READY_TIMEOUT_SEC
    with pytest.raises(FatalIdleWorker, match="ready"):
        runtime.refresh.tick()
    assert runtime.consumer.task_consumer.queues == []


@pytest.mark.parametrize("running", [False, True])
def test_reload_timeout_never_forks_from_mutating_registry(runtime, running):
    start_reload(runtime)
    if running:
        runtime.future.set_running_or_notify_cancel()
    runtime.now[0] += runtime.refresh.RELOAD_TIMEOUT_SEC
    with pytest.raises(FatalIdleWorker, match="reload timed out"):
        runtime.refresh.tick()
    assert runtime.future.cancelled() is not running
    assert runtime.events == ["shrink"]


def test_reload_exception_never_exposes_partially_loaded_registry(runtime):
    start_reload(runtime)
    runtime.future.set_exception(RuntimeError("registry import failed"))
    with pytest.raises(FatalIdleWorker, match="reloading: RuntimeError"):
        runtime.refresh.tick()
    assert runtime.events == ["shrink"]
    assert not consumer_is_ready(runtime.consumer, runtime.names, prefork=True)


def test_queue_restore_error_does_not_report_ready(runtime):
    start_reload(runtime)
    runtime.future.set_result(False)
    runtime.refresh.tick()
    make_ready(runtime)
    runtime.consumer.add_task_queue = Mock(side_effect=ConnectionError())
    with pytest.raises(FatalIdleWorker, match="ConnectionError"):
        runtime.refresh.tick()
    assert runtime.refresh.in_progress


def test_queue_pause_failure_does_not_kill_active_pipeline(runtime):
    runtime.raw._cache["request"] = object()
    runtime.consumer.cancel_task_queue = Mock(side_effect=ConnectionError())
    runtime.refresh.request()
    runtime.now[0] = 100_000
    runtime.refresh.tick()
    assert runtime.events == []
    runtime.raw._cache.clear()
    with pytest.raises(FatalIdleWorker, match="pausing queues"):
        runtime.refresh.tick()


def test_readiness_requires_connection_subscriptions_and_ready_child(runtime):
    assert not consumer_is_ready(runtime.consumer, runtime.names, prefork=True)
    make_ready(runtime)
    assert consumer_is_ready(runtime.consumer, runtime.names, prefork=True)
    runtime.consumer.cancel_task_queue(runtime.names[0])
    assert not consumer_is_ready(runtime.consumer, runtime.names, prefork=True)
    runtime.consumer.add_task_queue(runtime.names[0])
    runtime.consumer.connection.close()
    assert not consumer_is_ready(runtime.consumer, runtime.names, prefork=True)
