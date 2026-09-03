import asyncio
import os
import signal
from contextlib import suppress

import grpc
from contracts.src.orchestrator.v1 import orchestrator_pb2_grpc
from sqlmodel import Session

from src.db import engine
from src.logger import logger
from src.modules.project.infra import db_models  # noqa: F403
from src.utils.waiting import wait_for_alembic_migrations, wait_for_db

import config

from .deps.execution_registry import get_task_execution_registry
from .deps.scheduler import init_task_scheduler
from .execution_supervisor import TaskExecutionSupervisor
from .listeners import CommandsStreamListener, EventsStreamListener, HeartbeatListener
from .servicers.orchestrator import OrchestratorServicer

GRACE_SECONDS = 2


def _wait_for_database_schema() -> None:
    with Session(engine) as session:
        wait_for_db(session)
        wait_for_alembic_migrations(
            session,
            release_path=config.PROJECT.RELEASE_FILE,
            timeout=config.POSTGRES.MIGRATION_WAIT_TIMEOUT_SEC,
        )


def _setup_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    stop_event: asyncio.Event,
    force_exit_event: asyncio.Event,
) -> None:
    """
    1-й сигнал -> graceful stop.
    2-й сигнал -> немедленный выход (os._exit).
    """
    counter = {"value": 0}

    def _on_signal() -> None:
        counter["value"] += 1
        if counter["value"] == 1:
            stop_event.set()
        else:
            force_exit_event.set()

    def _install_signal_handler(sig: signal.Signals) -> None:
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(_on_signal))

    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError, ValueError):
            _install_signal_handler(sig)

    with suppress(AttributeError, NotImplementedError):
        if hasattr(signal, "SIGBREAK"):
            _install_signal_handler(signal.SIGBREAK)


async def _graceful_server_run(server: grpc.aio.Server, host: str, port: int) -> None:
    stop_event = asyncio.Event()
    force_exit_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    _setup_signal_handlers(loop, stop_event, force_exit_event)

    await server.start()
    logger.info("[orchestrator_celery] gRPC started", host=host, port=port)

    termination_task = asyncio.create_task(server.wait_for_termination(), name="grpc-termination")
    stop_waiter = asyncio.create_task(stop_event.wait(), name="stop-event-wait")

    try:
        done, _ = await asyncio.wait(
            {termination_task, stop_waiter},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if stop_waiter in done and not termination_task.done():
            logger.info("Stopping gRPC gracefully...")
            await server.stop(grace=GRACE_SECONDS)
            await termination_task

    except asyncio.CancelledError:
        logger.info("Cancelled: stopping gRPC gracefully...")
        await asyncio.shield(server.stop(grace=GRACE_SECONDS))
        await asyncio.shield(server.wait_for_termination())

    finally:
        for task in (termination_task, stop_waiter):
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

        if force_exit_event.is_set():
            os._exit(130)

        logger.info("gRPC stopped")


async def _stop_services(
    scheduler,
    heartbeat_listener,
    events_listener,
    commands_listener,
    execution_supervisor,
) -> None:
    await execution_supervisor.stop()
    await commands_listener.stop()
    await events_listener.stop()
    await heartbeat_listener.stop()
    await scheduler.stop()


async def serve() -> None:
    _wait_for_database_schema()

    scheduler = init_task_scheduler()
    execution_supervisor = TaskExecutionSupervisor(
        registry=get_task_execution_registry(),
        scheduler=scheduler,
    )
    heartbeat_listener = HeartbeatListener()
    events_listener = EventsStreamListener()
    commands_listener = CommandsStreamListener()

    await scheduler.start()
    await execution_supervisor.start()
    await heartbeat_listener.start()
    await events_listener.start()
    await commands_listener.start()

    server = grpc.aio.server(
        options=[
            ("grpc.max_send_message_length", 100 * 1024 * 1024),
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ],
    )
    orchestrator_pb2_grpc.add_OrchestratorServicer_to_server(OrchestratorServicer(), server)

    server.add_insecure_port(f"{config.ORCHESTRATOR.ORCHESTRATOR_HOST}:{config.ORCHESTRATOR.ORCHESTRATOR_PORT}")
    logger.info("gRPC starting")

    try:
        await _graceful_server_run(
            server,
            host=config.ORCHESTRATOR.ORCHESTRATOR_HOST,
            port=config.ORCHESTRATOR.ORCHESTRATOR_PORT,
        )
    finally:
        try:
            await asyncio.shield(
                _stop_services(
                    scheduler,
                    heartbeat_listener,
                    events_listener,
                    commands_listener,
                    execution_supervisor
                )
            )
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(serve())
