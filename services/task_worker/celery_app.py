import asyncio
import multiprocessing
import sys
import time
from typing import Any

import redis
from billiard.exceptions import WorkerLostError
from celery.signals import (
    task_failure,
    worker_before_create_process,
    worker_init,
    worker_process_init,
    worker_process_shutdown,
    worker_ready,
    worker_shutdown,
)
from kombu import Exchange, Queue
from sqlmodel import Session, select

from core.db.connect import close_clickhouse_pool_managers

from services.task_worker.deps import get_extension_manager
from services.task_worker.deps.pipeline_callbacks import close_redis_clients
from services.task_worker.execution_slot import mark_execution_slot_idle
from services.task_worker.heartbeat import HeartbeatSender
from services.task_worker.helpers import get_async_runner, get_worker_id

from src.db import AsyncSessionLocal, async_engine, engine
from src.enums import ExtensionDepsStatus
from src.infra.celery import create_celery_app
from src.logger import (
    add_db_log_sink,
    add_websocket_log_sink,
    db_sink as logger_db_sink,
    logger,
)
from src.logger._multiprocessing.mp_child_sink import add_mp_queue_sink_child
from src.logger._multiprocessing.mp_parent_listener import start_mp_log_listener
from src.models.extension import ExtensionRecord
from src.modules.task_execution.domain.types import TaskTerminationReason
from src.runtime.async_runtime import shared_ws_forward
from src.utils.extensions import ensure_extension_deps_installed
from src.utils.waiting import wait_for_alembic_migrations, wait_for_db

import config

celery_app = create_celery_app("task_worker")

if config.TASK_WORKER.CELERY_WORKER_CONCURRENCY != 1:
    raise RuntimeError(
        "One task_worker container must execute exactly one pipeline task; "
        "set CELERY_WORKER_CONCURRENCY=1."
    )

_TASKS_EXCHANGE = Exchange(config.CELERY.CELERY_TASKS_QUEUE, type="direct")
_DEPS_EXCHANGE = Exchange(config.CELERY.CELERY_DEPS_EXCHANGE, type="direct")

celery_app.conf.update(
    task_default_queue=config.CELERY.CELERY_TASKS_QUEUE,
    task_default_exchange_type="direct",
    task_default_routing_key=config.CELERY.CELERY_TASKS_QUEUE,
    worker_prefetch_multiplier=config.CELERY.CELERY_WORKER_PREFETCH_MULTIPLIER,
    task_acks_late=config.CELERY.CELERY_TASK_ACKS_LATE,
    # Pipeline tasks can have external side effects.  A lost child must be
    # reconciled by PostgreSQL lifecycle state, never silently re-run by Celery.
    task_reject_on_worker_lost=False,
    worker_pool="prefork",
    worker_concurrency=1,
    worker_disable_prefetch=True,
    worker_max_tasks_per_child=config.TASK_WORKER.CELERY_WORKER_MAX_TASKS_PER_CHILD,
    worker_max_memory_per_child=config.TASK_WORKER.CELERY_WORKER_MAX_MEMORY_PER_CHILD,
    imports=("services.task_worker.tasks.worker_tasks",),
    task_track_started=False,
    task_ignore_result=True,
    worker_send_task_events=False,
    task_send_sent_event=False,
    task_queues=[
        Queue(
            config.CELERY.CELERY_TASKS_QUEUE,
            exchange=_TASKS_EXCHANGE,
            routing_key=config.CELERY.CELERY_TASKS_QUEUE,
        ),
        Queue(
            config.CELERY.CELERY_DEPS_QUEUE,
            exchange=_DEPS_EXCHANGE,
            routing_key=config.CELERY.CELERY_DEPS_QUEUE,
        ),
    ],
)

_ws_forward_client: object | None = None
_heartbeat: HeartbeatSender | None = None
_child_sinks_initialized: bool = False
_child_local_sinks_initialized: bool = False
_child_mp_sink_handler_id: int | None = None
_child_uses_local_sinks: bool = False
_child_ws_init_attempted: bool = False
_extension_runtime_initialized: bool = False
_extension_runtime_generation: tuple[tuple[str, ...], ...] | None = None
_mp_log_queue: Any | None = None
_mp_log_listener_thread: object | None = None
_mp_log_stop_event: Any | None = None
_CHILD_LOG_SINK_INIT_TIMEOUT_SEC = 3.0


def _is_prefork_pool() -> bool:
    return str(celery_app.conf.worker_pool).lower() == "prefork"


def _is_main_process() -> bool:
    return multiprocessing.current_process().name == "MainProcess"


def _ensure_mp_log_bridge_transport() -> None:
    global _mp_log_queue, _mp_log_stop_event

    if not _is_prefork_pool() or not _is_main_process():
        return

    if _mp_log_queue is None:
        _mp_log_queue = multiprocessing.Queue(maxsize=config.LOGGING.LOG_QUEUE_MAXSIZE)

    if _mp_log_stop_event is None:
        _mp_log_stop_event = multiprocessing.Event()


def _start_mp_log_bridge_listener() -> None:
    global _mp_log_listener_thread

    if not _is_prefork_pool() or not _is_main_process():
        return

    _ensure_mp_log_bridge_transport()
    if _mp_log_queue is None or _mp_log_stop_event is None:
        return

    if _mp_log_listener_thread is not None and _mp_log_listener_thread.is_alive():
        return

    _mp_log_stop_event.clear()
    # This bridge is intentionally local-only. The Celery MainProcess may fork
    # replacement children at any time, so it must never turn child payloads into
    # gRPC/WS calls. Each already-forked execution child owns its own WS client.
    _mp_log_listener_thread = start_mp_log_listener(
        _mp_log_queue,
        stop_flag_callable=_mp_log_stop_event.is_set,
        drain_timeout=max(0.2, float(config.LOGGING.LOG_FLUSH_INTERVAL_SEC)),
    )


def _stop_mp_log_bridge_listener() -> None:
    global _mp_log_listener_thread, _mp_log_queue, _mp_log_stop_event

    if _mp_log_stop_event is not None:
        _mp_log_stop_event.set()

    if _mp_log_listener_thread is not None:
        _mp_log_listener_thread.join(timeout=5.0)
        _mp_log_listener_thread = None

    if _mp_log_queue is not None:
        _mp_log_queue.close()
        _mp_log_queue.join_thread()
        _mp_log_queue = None

    _mp_log_stop_event = None


def wait_for_redis(timeout: float = 60.0, interval: float = 1.0) -> None:
    redis_client = redis.Redis(
        host=config.VALKEY.VALKEY_HOST,
        port=config.VALKEY.VALKEY_PORT,
        password=config.VALKEY.VALKEY_PASSWORD,
    )
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            redis_client.ping()
            logger.info("VALKEY is available for Celery broker")
            return

        except Exception as exc:
            remaining = max(0.0, deadline - time.time())
            logger.info(
                f"Waiting for VALKEY to start (retry in {interval:.1f}s, left ~{remaining:.1f}s): {exc}"
            )
            time.sleep(interval)

    raise TimeoutError("VALKEY did not become available within the timeout period")


async def _init_db_log_sink() -> None:
    if config.LOGGING.LOG_TO_DB and logger_db_sink.DB_SINK_HANDLER_ID is None:
        try:
            loop = asyncio.get_running_loop()
            add_db_log_sink(
                loop=loop,
                level=config.LOGGING.LOG_LEVEL,
                engine=async_engine,
            )
        except Exception as exc:
            logger.error(f"Failed to add DB log sink: {exc}")


async def _init_ws_log_sink() -> None:
    global _ws_forward_client
    if config.LOGGING.LOG_TO_WS and _ws_forward_client is None:
        try:
            loop = asyncio.get_running_loop()
            _ws_forward_client = await shared_ws_forward.get()
            add_websocket_log_sink(
                send_message_callback=_ws_forward_client.send_message,
                level=config.LOGGING.LOG_LEVEL,
                loop=loop,
            )
            logger.info("WebSocket log sink registered via gRPC forward.")
        except Exception as exc:
            logger.error(f"Failed to add WebSocket log sink: {exc}")


async def _init_log_sinks() -> None:
    await _init_db_log_sink()
    await _init_ws_log_sink()


async def _ensure_log_sinks_for_task_process_async() -> None:
    global _child_sinks_initialized, _child_local_sinks_initialized
    global _child_mp_sink_handler_id, _child_uses_local_sinks, _child_ws_init_attempted

    if _child_sinks_initialized:
        return

    if _mp_log_queue is not None:
        try:
            _child_mp_sink_handler_id = add_mp_queue_sink_child(
                log_queue=_mp_log_queue,
                level=config.LOGGING.LOG_LEVEL,
            )
            _child_uses_local_sinks = False
            _child_sinks_initialized = True

            # The multiprocessing bridge only feeds local/DB logging in the
            # MainProcess. WS forwarding is process-scoped in this already-forked
            # child, so future pool forks never inherit an active gRPC runtime.
            # Forwarding is optional: an unavailable Gateway must never block a task.
            if config.LOGGING.LOG_TO_WS and not _child_ws_init_attempted:
                _child_ws_init_attempted = True
                try:
                    await asyncio.wait_for(
                        _init_ws_log_sink(),
                        timeout=_CHILD_LOG_SINK_INIT_TIMEOUT_SEC,
                    )
                except TimeoutError:
                    logger.warning(
                        "Timed out while initializing child WebSocket log sink; "
                        "continuing without WS logging for this worker child."
                    )
            return
        except Exception as exc:
            _child_sinks_initialized = False
            _child_uses_local_sinks = False
            logger.warning(
                f"Child log sink initialization failed, falling back to local sinks: {exc}"
            )

    try:
        await asyncio.wait_for(
            _init_log_sinks(),
            timeout=_CHILD_LOG_SINK_INIT_TIMEOUT_SEC,
        )
    except TimeoutError:
        logger.warning("Timed out while initializing child log sinks; continue without waiting.")
    except Exception as exc:
        logger.warning(f"Child log sink initialization failed: {exc}")
    finally:
        # Logging is auxiliary. One bounded initialization attempt per child is
        # enough; task execution must not repeatedly stall while logging is down.
        _child_local_sinks_initialized = True
        _child_uses_local_sinks = True
        _child_sinks_initialized = True


def ensure_log_sinks_for_task_process() -> None:
    runner = get_async_runner()
    runner.run(_ensure_log_sinks_for_task_process_async())


async def _finalize_task_process_logging_async() -> None:
    global _child_sinks_initialized, _child_local_sinks_initialized
    global _child_mp_sink_handler_id, _child_uses_local_sinks

    await logger.complete()

    if _child_mp_sink_handler_id is not None:
        logger.remove(_child_mp_sink_handler_id)
        _child_mp_sink_handler_id = None

    if _child_uses_local_sinks and _child_local_sinks_initialized:
        await _shutdown_log_sinks()
    else:
        _child_sinks_initialized = False
        _child_local_sinks_initialized = False
        _child_uses_local_sinks = False


def finalize_task_process_logging() -> None:
    runner = get_async_runner()
    runner.run(_finalize_task_process_logging_async())


async def _shutdown_log_sinks() -> None:
    global _ws_forward_client, _child_sinks_initialized, _child_ws_init_attempted
    global _child_local_sinks_initialized, _child_mp_sink_handler_id, _child_uses_local_sinks

    if _ws_forward_client is not None:
        try:
            await _ws_forward_client.close()
            logger.info("gRPC WS forward client closed")
        except Exception as exc:
            logger.warning(f"Failed to close gRPC WS client: {exc}")
        finally:
            _ws_forward_client = None

    await logger.complete()

    if logger_db_sink.DB_SINK_HANDLER_ID is not None:
        logger.remove(logger_db_sink.DB_SINK_HANDLER_ID)
        logger_db_sink.DB_SINK_HANDLER_ID = None

    if _child_mp_sink_handler_id is not None:
        logger.remove(_child_mp_sink_handler_id)
        _child_mp_sink_handler_id = None

    if logger_db_sink.DB_SINK is not None:
        try:
            await logger_db_sink.DB_SINK.close()
        except Exception:
            logger.exception("Error while closing DB sink")
        finally:
            logger_db_sink.DB_SINK = None

    _child_sinks_initialized = False
    _child_local_sinks_initialized = False
    _child_uses_local_sinks = False
    _child_ws_init_attempted = False


async def _read_extension_runtime_generation(
    *,
    required_extension_names: set[str] | None = None,
) -> tuple[tuple[str, ...], ...]:
    async with AsyncSessionLocal() as session:
        records = list((await session.execute(select(ExtensionRecord))).scalars().all())

    by_name = {record.name: record for record in records}
    for name in sorted(required_extension_names or ()):
        record = by_name.get(name)
        if record is None:
            raise RuntimeError(f"Required extension '{name}' is missing")
        if not record.is_installed:
            raise RuntimeError(f"Required extension '{name}' is not installed")
        if not record.is_enabled:
            raise RuntimeError(f"Required extension '{name}' is disabled")
        if record.deps_status != ExtensionDepsStatus.READY:
            raise RuntimeError(
                f"Required extension '{name}' dependencies are not READY: {record.deps_status.value}"
            )
        if record.error_message:
            raise RuntimeError(
                f"Required extension '{name}' is unavailable: {record.error_message}"
            )

    return tuple(
        sorted(
            (
                record.name,
                str(record.current_version or ""),
                str(record.install_path or ""),
                "1" if record.is_installed else "0",
                "1" if record.is_enabled else "0",
                record.deps_status.value,
                str(record.error_message or ""),
                record.installed_at.isoformat() if record.installed_at is not None else "",
            )
            for record in records
        )
    )


async def _initialize_extension_runtime_before_pool() -> None:
    """Load extension nodes before task execution; parent preload is fork-inheritable."""
    global _extension_runtime_initialized, _extension_runtime_generation
    if _extension_runtime_initialized:
        return
    with Session(engine) as session:
        wait_for_db(session)
        wait_for_alembic_migrations(
            session,
            release_path=config.PROJECT.RELEASE_FILE,
            timeout=config.POSTGRES.MIGRATION_WAIT_TIMEOUT_SEC,
        )

    try:
        await ensure_extension_deps_installed()

        logger.debug("Task worker startup: syncing installed extensions before pool init")
        async with AsyncSessionLocal() as session:
            manager = await get_extension_manager(session=session)
            try:
                await manager.sync_installed_extensions()
            finally:
                distributor_client = getattr(manager, "distributor_client", None)
                if distributor_client is not None:
                    await distributor_client.aclose()
        _extension_runtime_generation = await _read_extension_runtime_generation()
        _extension_runtime_initialized = True
        logger.debug("Task worker startup: extension runtime initialized before pool init")
    finally:
        # asyncio.run() closes its loop after this coroutine. Do not leave pooled
        # async connections bound to that loop or inherited by prefork children.
        await async_engine.dispose()


async def _ensure_extension_runtime_for_task_process_async(
    *,
    required_extension_names: set[str] | None = None,
) -> None:
    """Reload a persistent child only when the authoritative extension revision changes."""
    global _extension_runtime_initialized, _extension_runtime_generation

    current_generation = await _read_extension_runtime_generation(
        required_extension_names=required_extension_names
    )
    if _extension_runtime_initialized and current_generation == _extension_runtime_generation:
        return

    # A READY status may have been produced by another homogeneous worker.
    # Install locally as well before importing the shared-volume runtime.
    await ensure_extension_deps_installed(raise_on_failure=True)
    async with AsyncSessionLocal() as session:
        manager = await get_extension_manager(session=session)
        try:
            await manager.sync_installed_extensions()
        finally:
            distributor_client = getattr(manager, "distributor_client", None)
            if distributor_client is not None:
                await distributor_client.aclose()

    _extension_runtime_generation = await _read_extension_runtime_generation(
        required_extension_names=required_extension_names
    )
    _extension_runtime_initialized = True


def ensure_extension_runtime_for_task_process(
    required_extension_names: set[str] | None = None,
) -> None:
    get_async_runner().run(
        _ensure_extension_runtime_for_task_process_async(
            required_extension_names=required_extension_names
        )
    )


async def _startup() -> None:
    global _ws_forward_client, _heartbeat

    wait_for_redis()
    _start_mp_log_bridge_listener()
    # The MainProcess can fork future Celery children. It may own the DB sink,
    # but it must never create the gRPC/WebSocket forwarding client.
    if config.LOGGING.LOG_TO_DB:
        await _init_db_log_sink()

    logger.info(f"Task worker {get_worker_id()} service starting up.")
    logger.info(f"LOG_LEVEL: {config.LOGGING.LOG_LEVEL}")
    logger.info(f"LOG_TO_WS: {config.LOGGING.LOG_TO_WS}")
    logger.info(f"LOG_TO_DB: {config.LOGGING.LOG_TO_DB}")

    _heartbeat = HeartbeatSender()
    await _heartbeat.start()
    logger.info("Heartbeat started")


async def _shutdown() -> None:
    global _heartbeat

    logger.info("Task worker service shutting down.")

    if _heartbeat is not None:
        try:
            await _heartbeat.stop()
            logger.info("Heartbeat stopped")
        except Exception as exc:
            logger.warning(f"Failed to stop heartbeat: {exc}")

    _stop_mp_log_bridge_listener()
    await _shutdown_log_sinks()
    try:
        await close_redis_clients()
        logger.info("Task worker Redis event clients closed")
    except Exception as exc:
        logger.warning(f"Failed to close task worker Redis event clients: {exc}")

    _heartbeat = None


@worker_before_create_process.connect
def _prepare_log_bridge_before_child_fork(**_kwargs) -> None:
    _ensure_mp_log_bridge_transport()


@worker_init.connect
def _init_extension_runtime_before_pool(**_kwargs) -> None:
    try:
        asyncio.run(_initialize_extension_runtime_before_pool())
    finally:
        # The synchronous health-check pool must not be inherited either.
        engine.dispose()


@worker_ready.connect
def _init_worker_main(**_kwargs) -> None:
    runner = get_async_runner()
    runner.run(_startup())


@worker_process_init.connect
def _init_worker_child(**_kwargs) -> None:
    """
    SpawnPoolWorker safety: ensure Celery fast trace locals are initialized.
    Without this, child may crash with:
    ValueError: not enough values to unpack (expected 3, got 0)
    in celery.app.trace.fast_trace_task.
    """
    engine.dispose()

    # Так как dispose() у AsyncEngine возвращает корутину,
    # а этот обработчик синхронный, используем простой трюк:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(async_engine.dispose())
        else:
            loop.run_until_complete(async_engine.dispose())
        logger.info("Success dispose db connection")
    except Exception as e:
        # Если цикла еще нет, SQLAlchemy сама создаст новый пул при первом запросе,
        # но принудительный dispose лучше сделать явно.
        logger.warning(f"Could not dispose async_engine: {e}")

    if not sys.platform.startswith("win"):
        return

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        from celery.app import trace as celery_trace

        if not celery_trace._localized:
            celery_trace.setup_worker_optimizations(celery_app)

        for task in celery_app.tasks.values():
            if getattr(task, "__trace__", None) is None:
                task.__trace__ = celery_trace.build_tracer(task.name, task, app=celery_app)
    except Exception as exc:
        logger.warning(f"Failed to initialize celery trace optimization in worker child: {exc}")
        try:
            from celery.app import trace as celery_trace

            celery_trace.reset_worker_optimizations(celery_app)
        except Exception as fallback_exc:
            logger.warning(
                f"Failed to disable celery fast trace fallback in worker child: {fallback_exc}"
            )

    # Do not perform network/log sink initialization here.
    # Child must become "UP" quickly; sink init is done lazily inside task execution.


async def _finalize_worker_lost_execution(task_id: str) -> None:
    from src.modules.task_execution.facade import build_task_execution_facade

    execution = build_task_execution_facade(celery_app=celery_app)
    finalized = await execution.finalize_reconciled.execute(
        task_id=task_id,
        termination_reason=TaskTerminationReason.WORKER_LOST,
        message="Celery execution child exited unexpectedly",
    )
    if finalized is None:
        logger.info(
            "WorkerLostError did not change authoritative task lifecycle",
            task_id=task_id,
        )
        return
    logger.error(
        "Finalized task after unexpected Celery execution child loss",
        task_id=task_id,
        status=finalized.status,
        termination_reason=finalized.termination_reason,
    )


@task_failure.connect
def _handle_execution_child_failure(
    *,
    sender=None,
    task_id: str | None = None,
    exception: BaseException | None = None,
    **_kwargs,
) -> None:
    """Handle prefork child loss in MainProcess without enabling Celery redelivery."""
    if not _is_main_process():
        return
    if getattr(sender, "name", None) != "task_worker.handle_task":
        return
    if task_id is None or not isinstance(exception, WorkerLostError):
        return

    # SIGTERM-based STOP/HARD_STOP revocation is reported by Celery as Terminated
    # and does not enter this signal branch. If a system kill races with an
    # existing PostgreSQL termination reason, task_execution precedence remains
    # authoritative in finalize_reconciled.
    mark_execution_slot_idle(task_id=task_id)
    try:
        get_async_runner().run(_finalize_worker_lost_execution(task_id))
    except Exception:
        logger.exception(
            "Failed to persist WORKER_LOST after Celery execution child loss",
            task_id=task_id,
        )


@worker_process_shutdown.connect
def _shutdown_worker_child(**_kwargs) -> None:
    runner = get_async_runner()
    # This hook stays fork-safe and does not rebuild the extension runtime.
    try:
        close_clickhouse_pool_managers()
    except Exception as exc:
        logger.warning(f"Failed to close ClickHouse HTTP pool managers: {exc}")
    finally:
        runner.stop()


@worker_shutdown.connect
def _shutdown_worker_main(**_kwargs) -> None:
    runner = get_async_runner()
    runner.run(_shutdown())
    runner.stop()
