import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import grpc
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from ws_forward.v1 import forward_pb2_grpc

from services.gateway.deps import (
    get_background_scheduler_manager,
    preload_node_documentation_repository,
)
from services.gateway.grpc.auth_interceptor import AuthInterceptor
from services.gateway.grpc.ws_forward_server import ForwardWSServicer
from services.gateway.metrics import MetricsUpdaterManager, get_metrics_cache
from services.gateway.update_runtime import get_system_state_monitor

from src.clients.denvic_extensions_distributor import DenvicExtensionsDistributor
from src.db import async_engine, engine
from src.logger import DB_SINK, DB_SINK_HANDLER_ID, logger
from src.managers.extension_manager import ExtensionManager

# from src.managers.dcc_manager import get_dcc_manager  # TODO: Waiting DDC v2 before fixes and implementation
from src.modules.app_settings.public import helpers as app_settings_helpers
from src.utils.cleanup import PgAdvisoryLock, clean_old_logs
from src.utils.extensions import ensure_extension_deps_installed
from src.utils.waiting import wait_for_db

import config


def scheduled_cleanup(
        db_engine,
        retention_days=config.LOGGING.LOGS_CLEANUP_TRESHOLD_DAYS,
        batch_size=config.LOGGING.LOGS_CLEANUP_BATCH_SIZE,
):
    threshold = datetime.now(UTC) - timedelta(days=retention_days)
    deleted = clean_old_logs(engine=db_engine, threshold=threshold, batch_size=batch_size)
    logger.info("Logs cleanup done. Deleted={} older than {}", deleted, threshold.isoformat())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.AI_MCP.validate()
    # dcc_manager = get_dcc_manager()  # TODO: Waiting DDC v2 before fixes and implementation
    metrics_manager: MetricsUpdaterManager | None = None
    system_state_monitor = get_system_state_monitor()

    with Session(engine) as session:
        wait_for_db(session)

    async with AsyncSession(async_engine) as session:
        await app_settings_helpers.ensure_setting_value(
            "dcc.connector_id",
            lambda: str(uuid4()),
            session=session,
            changed_by="system",
            change_reason="Initialize DCC connector id",
            force=True
        )
        await session.commit()

    await ensure_extension_deps_installed()
    distributor_client = DenvicExtensionsDistributor(config.EXTENSIONS.DISTRIBUTOR_URL)
    try:
        async with AsyncSession(async_engine) as session:
            extension_manager = ExtensionManager(
                session, distributor_client, gateway_runtime=True
            )
            await extension_manager.sync_installed_extensions()
    finally:
        await distributor_client.aclose()

    loop = asyncio.get_running_loop()
    # init_future = asyncio.create_task(dcc_manager.init())  # TODO: Waiting DDC v2 before fixes and implementation

    if config.LOGGING.LOG_TO_DB:
        try:
            from src.logger import add_db_log_sink
            loop = asyncio.get_event_loop()
            add_db_log_sink(
                loop=loop,
                level=config.LOGGING.LOG_LEVEL,
                engine=async_engine,
            )

        except Exception as e:
            logger.error(f"Failed to add DB log sink: {e}")

    logger.info("Gateway service starting up.")
    logger.info(f"LOG_LEVEL: {config.LOGGING.LOG_LEVEL}")
    logger.info(f"LOG_TO_WS: {config.LOGGING.LOG_TO_WS}")
    logger.info(f"LOG_TO_DB: {config.LOGGING.LOG_TO_DB}")

    if config.LOGGING.LOG_TO_WS:
        try:
            from services.gateway.deps import get_websocket_manager
            ws_manager = get_websocket_manager()

            grpc_server = grpc.aio.server(
                options=[
                    ("grpc.keepalive_permit_without_calls", 1),
                    ("grpc.http2.max_pings_without_data", 10),
                    ("grpc.http2.min_ping_interval_without_data_ms", 60000),
                    ("grpc.http2.min_time_between_pings_ms", 60 * 1000),

                    ("grpc.max_send_message_length", config.WS_FORWARD.GRPC_FORWARD_SERVICE_MAX_SEND_MESSAGE_LEN_MB * 1024 * 1024),
                    ("grpc.max_receive_message_length",
                     config.WS_FORWARD.GRPC_FORWARD_SERVICE_MAX_RECEIVE_MESSAGE_LEN_MB * 1024 * 1024),
                    ("grpc.keepalive_time_ms", 10 * 60 * 60 * 1000),
                    ("grpc.keepalive_timeout_ms", 10 * 60 * 60 * 1000),
                ],
                interceptors=[
                    AuthInterceptor(
                        expected_token=config.WS_FORWARD.GRPC_FORWARD_SERVICE_TOKEN
                    )
                ]
            )

            forward_pb2_grpc.add_ForwardWSServicer_to_server(
                ForwardWSServicer(ws_manager), grpc_server
            )

            grpc_server.add_insecure_port(f"{config.WS_FORWARD.GRPC_FORWARD_SERVICE_HOST}:{config.WS_FORWARD.GRPC_FORWARD_SERVICE_PORT}")
            await grpc_server.start()
            logger.info(f"gRPC ForwardWS started on {config.WS_FORWARD.GRPC_FORWARD_SERVICE_URL}")

            _app.state._grpc_waiter = asyncio.create_task(
                grpc_server.wait_for_termination())  # type: ignore[attr-defined]
            _app.state.grpc_server = grpc_server  # type: ignore[attr-defined]

        except Exception as e:
            logger.exception(f"Failed to start gRPC ForwardWS: {e}")

        try:
            from services.gateway.deps import get_websocket_manager

            from src.logger import add_websocket_log_sink

            loop = asyncio.get_event_loop()
            connection_manager = get_websocket_manager()
            add_websocket_log_sink(
                send_message_callback=connection_manager.send_personal_message,
                level=config.LOGGING.LOG_LEVEL,
                loop=loop
            )
        except Exception as e:
            logger.error(f"Failed to add WebSocket log sink: {e}")

    logger.info(f"Allow origins: {config.GATEWAY.GATEWAY_ORIGINS}")

    node_documentation_repository = preload_node_documentation_repository()
    logger.info(
        "Preloaded node documentation for {} nodes.",
        len(node_documentation_repository.get_documented_node_names()),
    )

    background_scheduler_manager = get_background_scheduler_manager()
    lock = PgAdvisoryLock(engine, key=config.LOGGING.LOGS_CLEANUP_ADVISORY_LOCK_KEY)

    background_scheduler_manager.schedule_job(
        func=lambda: scheduled_cleanup(engine),
        job_id="clean-old-logs",
        cron=config.LOGGING.LOGS_CLEANUP_CRON,
        jitter=600,
        replace_existing=True,
        lock_ctx=lock,
    )

    if config.METRICS.ENABLED:
        metrics_manager = MetricsUpdaterManager(get_metrics_cache())
        await metrics_manager.start()
        _app.state.metrics_manager = metrics_manager  # type: ignore[attr-defined]

    await system_state_monitor.start()

    yield
    logger.info("Gateway service shutting down.")
    await system_state_monitor.close()
    background_scheduler_manager.shutdown(wait=False)

    if metrics_manager is not None:
        await metrics_manager.stop()

    if getattr(_app.state, "grpc_server", None) is not None:  # type: ignore[attr-defined]
        try:
            await _app.state.grpc_server.stop(grace=5)  # type: ignore[attr-defined]
            waiter = getattr(_app.state, "_grpc_waiter", None)  # type: ignore[attr-defined]
            if waiter:
                await waiter

            logger.info("gRPC ForwardWS stopped.")

        except Exception as e:
            logger.exception("Error while stopping gRPC server", e)

    if DB_SINK_HANDLER_ID is not None:
        logger.remove(DB_SINK_HANDLER_ID)

    if DB_SINK is not None:
        try:
            await DB_SINK.close()
        except Exception as e:
            logger.exception("Error while closing DB sink", e)
