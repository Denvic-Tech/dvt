from __future__ import annotations

import asyncio
import queue
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from billiard.exceptions import WorkerLostError

from services.task_worker import celery_app

from src.logger import db_sink as logger_db_sink


def test_task_worker_uses_configured_visibility_timeout() -> None:
    timeout = celery_app.config.CELERY.CELERY_VISIBILITY_TIMEOUT_SEC

    assert celery_app.celery_app.conf.broker_transport_options["visibility_timeout"] == timeout
    assert (
        celery_app.celery_app.conf.result_backend_transport_options["visibility_timeout"]
        == timeout
    )
    assert celery_app.celery_app.conf.visibility_timeout == timeout


def test_extension_runtime_is_initialized_before_prefork_pool(monkeypatch) -> None:
    events: list[str] = []

    async def _fake_initialize_extension_runtime() -> None:
        events.append("extensions.initialized")

    class _FakeEngine:
        def dispose(self) -> None:
            events.append("engine.disposed")

    monkeypatch.setattr(
        celery_app,
        "_initialize_extension_runtime_before_pool",
        _fake_initialize_extension_runtime,
    )
    monkeypatch.setattr(celery_app, "engine", _FakeEngine())

    celery_app._init_extension_runtime_before_pool()

    assert events == ["extensions.initialized", "engine.disposed"]


@pytest.mark.asyncio
async def test_extension_runtime_syncs_and_closes_pre_fork_resources(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(celery_app, "_extension_runtime_initialized", False)

    class _FakeSyncSessionContext:
        def __enter__(self):
            events.append("db.session.open")
            return object()

        def __exit__(self, *_args) -> None:
            events.append("db.session.close")

    class _FakeAsyncSessionContext:
        async def __aenter__(self):
            events.append("async_db.session.open")
            return object()

        async def __aexit__(self, *_args) -> None:
            events.append("async_db.session.close")

    class _FakeDistributorClient:
        async def aclose(self) -> None:
            events.append("distributor.close")

    class _FakeManager:
        distributor_client = _FakeDistributorClient()

        async def sync_installed_extensions(self) -> None:
            events.append("extensions.sync")

        async def close(self) -> None:
            await self.distributor_client.aclose()

    class _FakeAsyncEngine:
        async def dispose(self) -> None:
            events.append("async_engine.dispose")

    async def _fake_ensure_extension_deps_installed() -> None:
        events.append("extensions.deps")

    async def _fake_get_extension_manager(*, session):
        assert session is not None
        events.append("extensions.manager")
        return _FakeManager()

    monkeypatch.setattr(celery_app, "Session", lambda _engine: _FakeSyncSessionContext())
    monkeypatch.setattr(celery_app, "wait_for_db", lambda _session: events.append("db.ready"))
    monkeypatch.setattr(
        celery_app,
        "wait_for_alembic_migrations",
        lambda _session, **_kwargs: events.append("migrations.ready"),
    )
    monkeypatch.setattr(
        celery_app,
        "ensure_extension_deps_installed",
        _fake_ensure_extension_deps_installed,
    )
    monkeypatch.setattr(
        celery_app,
        "AsyncSessionLocal",
        lambda: _FakeAsyncSessionContext(),
    )
    monkeypatch.setattr(celery_app, "get_extension_manager", _fake_get_extension_manager)
    monkeypatch.setattr(celery_app, "async_engine", _FakeAsyncEngine())

    async def _fake_generation(**_kwargs):
        return (("base",),)

    monkeypatch.setattr(celery_app, "_read_extension_runtime_generation", _fake_generation)

    await celery_app._initialize_extension_runtime_before_pool()

    assert celery_app._extension_runtime_initialized is True
    assert events == [
        "db.session.open",
        "db.ready",
        "migrations.ready",
        "db.session.close",
        "extensions.deps",
        "async_db.session.open",
        "extensions.manager",
        "extensions.sync",
        "distributor.close",
        "async_db.session.close",
        "async_engine.dispose",
    ]


@pytest.mark.asyncio
async def test_spawned_child_lazy_extension_bootstrap_runs_once(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(celery_app, "_extension_runtime_initialized", False)
    monkeypatch.setattr(celery_app, "_extension_runtime_generation", None)

    async def _read_generation(**_kwargs):
        return (("extension-a", "1"),)

    async def _deps(**_kwargs):
        calls.append("deps")

    class _SessionContext:
        async def __aenter__(self):
            return object()
        async def __aexit__(self, *_args):
            return False

    class _Distributor:
        async def aclose(self):
            calls.append("close")

    class _Manager:
        distributor_client = _Distributor()

        async def sync_installed_extensions(self):
            calls.append("sync")

        async def close(self):
            await self.distributor_client.aclose()

    async def _manager(*, session):
        assert session is not None
        return _Manager()

    monkeypatch.setattr(celery_app, "_read_extension_runtime_generation", _read_generation)
    monkeypatch.setattr(celery_app, "ensure_extension_deps_installed", _deps)
    monkeypatch.setattr(celery_app, "AsyncSessionLocal", lambda: _SessionContext())
    monkeypatch.setattr(celery_app, "get_extension_manager", _manager)

    assert await celery_app._ensure_extension_runtime_for_task_process_async() is True
    assert await celery_app._ensure_extension_runtime_for_task_process_async() is False

    assert calls == ["deps", "sync", "close"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("old_generation", "new_generation"),
    [
        ((), (("extension-a", "1"),)),
        ((("extension-a", "1"),), (("extension-a", "2"),)),
    ],
)
async def test_process_runtime_reloads_once_for_extension_install_or_update(
    monkeypatch,
    old_generation,
    new_generation,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(celery_app, "_extension_runtime_initialized", True)
    monkeypatch.setattr(celery_app, "_extension_runtime_generation", old_generation)

    async def _generation(**_kwargs):
        return new_generation

    async def _deps(**_kwargs):
        calls.append("deps")

    class _SessionContext:
        async def __aenter__(self):
            return object()
        async def __aexit__(self, *_args):
            return False

    class _Manager:
        distributor_client = None

        async def sync_installed_extensions(self):
            calls.append("registry.reload")

        async def close(self):
            return None

    async def _manager(*, session):
        assert session is not None
        return _Manager()

    monkeypatch.setattr(celery_app, "_read_extension_runtime_generation", _generation)
    monkeypatch.setattr(celery_app, "ensure_extension_deps_installed", _deps)
    monkeypatch.setattr(celery_app, "AsyncSessionLocal", lambda: _SessionContext())
    monkeypatch.setattr(celery_app, "get_extension_manager", _manager)

    assert await celery_app._ensure_extension_runtime_for_task_process_async(
        required_extension_names={"extension-a"}
    ) is True
    assert await celery_app._ensure_extension_runtime_for_task_process_async(
        required_extension_names={"extension-a"}
    ) is False

    assert calls == ["deps", "registry.reload"]
    assert celery_app._extension_runtime_generation == new_generation


def test_recycled_spawned_child_starts_with_fresh_extension_bootstrap(monkeypatch) -> None:
    class _Runner:
        def __init__(self):
            self.calls = 0

        def run(self, coro):
            self.calls += 1
            coro.close()
            return False

    runner = _Runner()
    monkeypatch.setattr(celery_app, "_extension_runtime_initialized", False)
    monkeypatch.setattr(celery_app, "get_async_runner", lambda: runner)

    celery_app.ensure_extension_runtime_for_task_process()

    assert runner.calls == 1


def test_changed_prefork_child_requests_warm_parent_refresh(monkeypatch) -> None:
    broadcasts: list[tuple[str, bool]] = []

    class _Control:
        def broadcast(self, command: str, *, reply: bool):
            broadcasts.append((command, reply))

    monkeypatch.setattr(celery_app, "_is_prefork_pool", lambda: True)
    monkeypatch.setattr(celery_app, "_is_main_process", lambda: False)
    monkeypatch.setattr(celery_app.celery_app, "control", _Control())

    celery_app.request_parent_extension_runtime_refresh()

    assert broadcasts == [("dvt_refresh_extension_runtime", False)]


def test_parent_refresh_control_uses_controller_and_reports_duplicate(monkeypatch) -> None:
    refresh = MagicMock()
    refresh.request.side_effect = [True, False]
    consumer = object()
    get_refresh = MagicMock(return_value=refresh)
    monkeypatch.setattr(celery_app, "_get_extension_parent_refresh", get_refresh)
    monkeypatch.setattr(celery_app, "_is_prefork_pool", lambda: True)
    monkeypatch.setattr(celery_app, "_is_main_process", lambda: True)

    assert celery_app._refresh_extension_runtime_control(SimpleNamespace(consumer=consumer)) == {
        "ok": "extension runtime refresh scheduled after current task drain"
    }
    assert celery_app._refresh_extension_runtime_control(SimpleNamespace(consumer=consumer)) == {
        "ok": "extension runtime refresh is already scheduled"
    }
    get_refresh.assert_called_with(consumer)


def test_refresh_controller_submits_reload_without_blocking_celery(monkeypatch) -> None:
    runner = MagicMock()
    monkeypatch.setattr(celery_app, "_extension_parent_refresh", None)
    monkeypatch.setattr(celery_app, "get_async_runner", lambda: runner)
    refresh = celery_app._get_extension_parent_refresh(object())
    assert refresh.submit_reload() is runner.submit.return_value
    runner.submit.call_args.args[0].close()
    runner.run.assert_not_called()


def test_heartbeat_readiness_is_false_while_refresh_is_in_progress(monkeypatch) -> None:
    monkeypatch.setattr(
        celery_app, "_extension_parent_refresh", SimpleNamespace(in_progress=True)
    )
    monkeypatch.setattr(celery_app, "consumer_is_ready", lambda *_args, **_kwargs: True)
    assert celery_app._execution_consumer_is_ready() is False


def test_main_process_worker_lost_signal_finalizes_authoritative_execution(monkeypatch) -> None:
    events: list[tuple[str, str]] = []

    async def _finalize(task_id: str) -> None:
        events.append(("finalize", task_id))

    class _Runner:
        def run(self, coro):
            return asyncio.run(coro)

    monkeypatch.setattr(celery_app, "_is_main_process", lambda: True)
    monkeypatch.setattr(
        celery_app,
        "mark_execution_slot_idle",
        lambda *, task_id=None: events.append(("idle", task_id)),
    )
    monkeypatch.setattr(celery_app, "get_async_runner", lambda: _Runner())
    monkeypatch.setattr(celery_app, "_finalize_worker_lost_execution", _finalize)

    celery_app._handle_execution_child_failure(
        sender=SimpleNamespace(name="task_worker.handle_task"),
        task_id="task-crashed",
        exception=WorkerLostError("child exited with signal 9"),
    )

    assert events == [("idle", "task-crashed"), ("finalize", "task-crashed")]


def test_main_process_intentional_or_regular_failure_is_not_worker_lost(monkeypatch) -> None:
    events: list[str] = []
    monkeypatch.setattr(celery_app, "_is_main_process", lambda: True)
    monkeypatch.setattr(
        celery_app,
        "mark_execution_slot_idle",
        lambda **_kwargs: events.append("idle"),
    )

    celery_app._handle_execution_child_failure(
        sender=SimpleNamespace(name="task_worker.handle_task"),
        task_id="task-failed",
        exception=RuntimeError("normal task failure"),
    )

    assert events == []


def test_prefork_child_uses_only_fork_safe_initialization(monkeypatch) -> None:
    events: list[str] = []

    monkeypatch.setattr(celery_app.sys, "platform", "linux")
    monkeypatch.setattr(celery_app.engine, "dispose", lambda: events.append("engine.dispose"))
    monkeypatch.setattr(
        celery_app.asyncio,
        "get_event_loop",
        lambda: (_ for _ in ()).throw(RuntimeError("event loop is not initialized")),
    )
    celery_app._init_worker_child()

    assert events == ["engine.dispose"]


@pytest.mark.asyncio
async def test_main_process_db_logging_does_not_create_ws_grpc_client(monkeypatch) -> None:
    events: list[str] = []

    async def _db_sink() -> None:
        events.append("db")

    async def _ws_sink() -> None:
        events.append("ws")

    monkeypatch.setattr(celery_app.config.LOGGING, "LOG_TO_DB", True)
    monkeypatch.setattr(celery_app, "wait_for_redis", lambda: None)
    monkeypatch.setattr(celery_app, "_start_mp_log_bridge_listener", lambda: None)
    monkeypatch.setattr(celery_app, "_init_db_log_sink", _db_sink)
    monkeypatch.setattr(celery_app, "_init_ws_log_sink", _ws_sink)

    class _Heartbeat:
        def __init__(self, *, is_ready):
            assert is_ready is celery_app._execution_consumer_is_ready

        async def start(self): return None

    monkeypatch.setattr(celery_app, "HeartbeatSender", _Heartbeat)

    await celery_app._startup()

    assert events == ["db"]


def test_main_process_log_bridge_never_receives_ws_forward_handler(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Thread:
        def is_alive(self):
            return True

    def _start_listener(_queue, *, stop_flag_callable, drain_timeout, payload_handler=None):
        captured["payload_handler"] = payload_handler
        captured["stop_flag_callable"] = stop_flag_callable
        captured["drain_timeout"] = drain_timeout
        return _Thread()

    monkeypatch.setattr(celery_app, "_is_main_process", lambda: True)
    monkeypatch.setattr(celery_app, "_is_prefork_pool", lambda: True)
    monkeypatch.setattr(celery_app, "_mp_log_queue", queue.Queue())
    monkeypatch.setattr(celery_app, "_mp_log_stop_event", threading.Event())
    monkeypatch.setattr(celery_app, "_mp_log_listener_thread", None)
    monkeypatch.setattr(celery_app, "start_mp_log_listener", _start_listener)
    monkeypatch.setattr(celery_app, "_ws_forward_client", None)

    celery_app._start_mp_log_bridge_listener()

    assert captured["payload_handler"] is None
    assert celery_app._ws_forward_client is None


@pytest.mark.asyncio
async def test_forked_child_owns_ws_client_even_when_using_parent_log_bridge(monkeypatch) -> None:
    init_ws = AsyncMock()
    monkeypatch.setattr(celery_app.config.LOGGING, "LOG_TO_WS", True)
    monkeypatch.setattr(celery_app, "_mp_log_queue", object())
    monkeypatch.setattr(celery_app, "_child_sinks_initialized", False)
    monkeypatch.setattr(celery_app, "_child_ws_init_attempted", False)
    monkeypatch.setattr(celery_app, "_child_mp_sink_handler_id", None)
    monkeypatch.setattr(celery_app, "add_mp_queue_sink_child", lambda **_kwargs: 17)
    monkeypatch.setattr(celery_app, "_init_ws_log_sink", init_ws)

    await celery_app._ensure_log_sinks_for_task_process_async()

    init_ws.assert_awaited_once()
    assert celery_app._child_mp_sink_handler_id == 17


@pytest.mark.asyncio
async def test_forked_child_ws_logging_timeout_is_best_effort_and_not_retried(monkeypatch) -> None:
    calls = 0

    class _FakeLogger:
        async def _awaitable(self):
            return None

        def complete(self):
            return self._awaitable()

        def remove(self, _handler_id: int) -> None:
            return None

        def warning(self, *_args, **_kwargs) -> None:
            return None

    async def _hanging_ws_sink() -> None:
        nonlocal calls
        calls += 1
        await asyncio.Event().wait()

    monkeypatch.setattr(celery_app, "logger", _FakeLogger())
    monkeypatch.setattr(celery_app.config.LOGGING, "LOG_TO_WS", True)
    monkeypatch.setattr(celery_app, "_mp_log_queue", object())
    monkeypatch.setattr(celery_app, "_child_sinks_initialized", False)
    monkeypatch.setattr(celery_app, "_child_local_sinks_initialized", False)
    monkeypatch.setattr(celery_app, "_child_mp_sink_handler_id", None)
    monkeypatch.setattr(celery_app, "_child_uses_local_sinks", False)
    monkeypatch.setattr(celery_app, "_child_ws_init_attempted", False)
    monkeypatch.setattr(celery_app, "_CHILD_LOG_SINK_INIT_TIMEOUT_SEC", 0.01)
    monkeypatch.setattr(celery_app, "add_mp_queue_sink_child", lambda **_kwargs: 17)
    monkeypatch.setattr(celery_app, "_init_ws_log_sink", _hanging_ws_sink)

    await asyncio.wait_for(
        celery_app._ensure_log_sinks_for_task_process_async(),
        timeout=0.2,
    )

    # Task-scoped finalization removes the MP sink and resets sink state. A
    # second initialization in the same process remains best-effort and must not
    # repeatedly block on the same unavailable WS endpoint.
    await celery_app._finalize_task_process_logging_async()
    await celery_app._ensure_log_sinks_for_task_process_async()

    assert calls == 1
    assert celery_app._child_ws_init_attempted is True
    assert celery_app._child_sinks_initialized is True
    assert celery_app._child_mp_sink_handler_id == 17
    assert celery_app._child_uses_local_sinks is False


@pytest.mark.asyncio
async def test_ready_startup_does_not_reload_extensions_after_pool_creation(monkeypatch) -> None:
    events: list[str] = []

    class _FakeHeartbeat:
        def __init__(self, *, is_ready):
            assert is_ready is celery_app._execution_consumer_is_ready

        async def start(self) -> None:
            events.append("heartbeat.start")

    monkeypatch.setattr(celery_app, "wait_for_redis", lambda: events.append("redis.wait"))
    monkeypatch.setattr(
        celery_app,
        "_start_mp_log_bridge_listener",
        lambda: events.append("logging.bridge"),
    )

    async def _fake_init_log_sinks() -> None:
        events.append("logging.sinks")

    monkeypatch.setattr(celery_app, "_init_log_sinks", _fake_init_log_sinks)
    monkeypatch.setattr(celery_app, "HeartbeatSender", _FakeHeartbeat)

    await celery_app._startup()

    assert events == [
        "redis.wait",
        "logging.bridge",
        "heartbeat.start",
    ]


@pytest.mark.asyncio
async def test_shutdown_closes_actual_db_sink_instance(monkeypatch):
    class _FakeLogger:
        def __init__(self):
            self.removed: list[int] = []

        def info(self, *_args, **_kwargs):
            return None

        def warning(self, *_args, **_kwargs):
            return None

        def error(self, *_args, **_kwargs):
            return None

        def exception(self, *_args, **_kwargs):
            return None

        async def _awaitable(self):
            return None

        def complete(self):
            return self._awaitable()

        def remove(self, handler_id: int):
            self.removed.append(handler_id)

    class _FakeSink:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    fake_logger = _FakeLogger()
    fake_sink = _FakeSink()
    close_redis_clients_called = {"value": False}

    async def _fake_close_redis_clients():
        close_redis_clients_called["value"] = True

    monkeypatch.setattr(celery_app, "logger", fake_logger)
    monkeypatch.setattr(celery_app, "_heartbeat", None)
    monkeypatch.setattr(celery_app, "_ws_forward_client", None)
    monkeypatch.setattr(celery_app, "close_redis_clients", _fake_close_redis_clients)

    previous_handler_id = logger_db_sink.DB_SINK_HANDLER_ID
    previous_sink = logger_db_sink.DB_SINK
    logger_db_sink.DB_SINK_HANDLER_ID = 17
    logger_db_sink.DB_SINK = fake_sink

    try:
        await celery_app._shutdown()
        assert fake_logger.removed == [17]
        assert fake_sink.closed is True
        assert close_redis_clients_called["value"] is True
        assert logger_db_sink.DB_SINK_HANDLER_ID is None
        assert logger_db_sink.DB_SINK is None
    finally:
        logger_db_sink.DB_SINK_HANDLER_ID = previous_handler_id
        logger_db_sink.DB_SINK = previous_sink


@pytest.mark.asyncio
async def test_finalize_task_process_logging_closes_local_sinks(monkeypatch):
    removed: list[int] = []
    shutdown_calls = {"count": 0}

    class _FakeLogger:
        async def _awaitable(self):
            return None

        def complete(self):
            return self._awaitable()

        def remove(self, handler_id: int):
            removed.append(handler_id)

    async def _fake_shutdown_log_sinks():
        shutdown_calls["count"] += 1

    monkeypatch.setattr(celery_app, "logger", _FakeLogger())
    monkeypatch.setattr(celery_app, "_shutdown_log_sinks", _fake_shutdown_log_sinks)
    monkeypatch.setattr(celery_app, "_child_sinks_initialized", True)
    monkeypatch.setattr(celery_app, "_child_local_sinks_initialized", True)
    monkeypatch.setattr(celery_app, "_child_uses_local_sinks", True)
    monkeypatch.setattr(celery_app, "_child_mp_sink_handler_id", None)

    await celery_app._finalize_task_process_logging_async()

    assert removed == []
    assert shutdown_calls["count"] == 1


@pytest.mark.asyncio
async def test_finalize_task_process_logging_removes_mp_handler(monkeypatch):
    removed: list[int] = []

    class _FakeLogger:
        async def _awaitable(self):
            return None

        def complete(self):
            return self._awaitable()

        def remove(self, handler_id: int):
            removed.append(handler_id)

    monkeypatch.setattr(celery_app, "logger", _FakeLogger())
    monkeypatch.setattr(celery_app, "_child_sinks_initialized", True)
    monkeypatch.setattr(celery_app, "_child_local_sinks_initialized", False)
    monkeypatch.setattr(celery_app, "_child_uses_local_sinks", False)
    monkeypatch.setattr(celery_app, "_child_mp_sink_handler_id", 23)

    await celery_app._finalize_task_process_logging_async()

    assert removed == [23]
    assert celery_app._child_mp_sink_handler_id is None
    assert celery_app._child_sinks_initialized is False
    assert celery_app._child_local_sinks_initialized is False
    assert celery_app._child_uses_local_sinks is False


def test_shutdown_worker_child_closes_clickhouse_pools_before_stopping_runner(monkeypatch):
    events: list[str] = []

    class _FakeRunner:
        def stop(self) -> None:
            events.append("runner.stop")

    def _get_async_runner() -> _FakeRunner:
        return _FakeRunner()

    monkeypatch.setattr(celery_app, "get_async_runner", _get_async_runner)
    monkeypatch.setattr(
        celery_app,
        "close_clickhouse_pool_managers",
        lambda: events.append("clickhouse.close"),
    )

    celery_app._shutdown_worker_child()

    assert events == ["clickhouse.close", "runner.stop"]


def test_shutdown_worker_child_stops_runner_when_clickhouse_cleanup_fails(monkeypatch):
    warnings: list[str] = []
    runner_stopped = {"value": False}

    class _FakeRunner:
        def stop(self) -> None:
            runner_stopped["value"] = True

    class _FakeLogger:
        def warning(self, message: str) -> None:
            warnings.append(message)

    def _raise_cleanup_error() -> None:
        raise RuntimeError("cleanup failed")

    def _get_async_runner() -> _FakeRunner:
        return _FakeRunner()

    monkeypatch.setattr(celery_app, "get_async_runner", _get_async_runner)
    monkeypatch.setattr(celery_app, "logger", _FakeLogger())
    monkeypatch.setattr(
        celery_app,
        "close_clickhouse_pool_managers",
        _raise_cleanup_error,
    )

    celery_app._shutdown_worker_child()

    assert runner_stopped["value"] is True
    assert warnings == ["Failed to close ClickHouse HTTP pool managers: cleanup failed"]


def test_runtime_inspect_reports_idle_pool_without_creating_refresh(monkeypatch):
    raw = SimpleNamespace(_pool=[], _cache={}, _processes=1, _fileno_to_inq={})
    consumer = SimpleNamespace(
        pool=SimpleNamespace(_pool=raw),
        task_consumer=SimpleNamespace(consuming_from=lambda _name: False),
    )
    monkeypatch.setattr(celery_app, "_extension_parent_refresh", None)
    monkeypatch.setattr(celery_app, "_is_prefork_pool", lambda: True)
    monkeypatch.setattr(celery_app, "_execution_consumer_is_ready", lambda: False)

    result = celery_app._inspect_extension_runtime(SimpleNamespace(consumer=consumer))
    assert result["ready"] is False
    assert result["active_queues"] == []
    assert result["refresh"]["pool_target_size"] == 1
    assert result["refresh"]["children"] == []
    assert celery_app._extension_parent_refresh is None
