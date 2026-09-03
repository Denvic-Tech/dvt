import time

from services.orchestrator.celery_app import celery_app
from services.orchestrator.deps.execution_registry import get_task_execution_registry
from services.orchestrator.deps.worker_registry import get_worker_registry
from services.orchestrator.execution_registry import TaskExecutionRecord

from src.logger import logger
from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.modules.task_execution.facade import build_task_execution_facade
from src.runtime.async_runtime import shared_ws_forward
from src.schemas.event import (
    NodeExecutionStatusEvent,
    NodeMetadataEvent,
    TaskExecutionStatusEvent,
    TaskExecutionTelemetryEvent,
)
from src.schemas.worker_event_payload import WorkerEventPayload


async def handle_worker_event(
    payload: WorkerEventPayload,
    *,
    forward_notifications: bool = True,
) -> None:
    event = payload.event

    if isinstance(event, TaskExecutionStatusEvent):
        await _handle_task_status(payload, event, forward_notifications=forward_notifications)
        return

    if isinstance(event, TaskExecutionTelemetryEvent):
        await _handle_task_execution_telemetry(payload, event)
        return

    if isinstance(event, NodeExecutionStatusEvent):
        await _handle_node_status(payload, event, forward_notifications=forward_notifications)
        return

    if isinstance(event, NodeMetadataEvent):
        await _handle_node_metadata(payload, event, forward_notifications=forward_notifications)
        return

    logger.warning("Unhandled worker event type", event_type=type(event))


async def _handle_task_status(
    payload: WorkerEventPayload,
    event: TaskExecutionStatusEvent,
    *,
    forward_notifications: bool = True,
) -> None:
    # Lifecycle is persisted synchronously by the task worker through the
    # task_execution facade. Stream events are notifications only.
    if event.status in (
        TaskExecutionStatus.SUCCESS,
        TaskExecutionStatus.ERROR,
        TaskExecutionStatus.CANCELLED,
    ):
        registry = get_task_execution_registry()
        await registry.remove(payload.task_id)
        get_worker_registry().mark_idle(
            worker_id=payload.worker_id,
            task_id=payload.task_id,
        )
        execution = build_task_execution_facade(celery_app=celery_app)
        await execution.release_nested_wait.execute(
            parent_task_id=payload.task_id,
            child_task_id=payload.task_id,
        )

    if not forward_notifications:
        return

    try:
        ws_forward_client = await shared_ws_forward.get()
        await ws_forward_client.send_message(
            event,
            user_id=payload.user_id,
            project_id=payload.project_id,
        )
    except Exception as e:
        logger.exception(f"Failed to send task status WS message: {e}")


async def _handle_task_execution_telemetry(
    payload: WorkerEventPayload,
    event: TaskExecutionTelemetryEvent,
) -> None:
    registry = get_task_execution_registry()
    get_worker_registry().mark_busy(worker_id=payload.worker_id, task_id=payload.task_id)
    await registry.upsert(
        TaskExecutionRecord(
            task_id=payload.task_id,
            worker_id=payload.worker_id,
            hostname=event.hostname,
            pid=event.pid,
            rss_bytes=event.rss_bytes,
            memory_limit_bytes=event.memory_limit_bytes,
            system_ram_used_percent=event.system_ram_used_percent,
            timestamp=time.time(),
        )
    )


async def _handle_node_status(
    payload: WorkerEventPayload,
    event: NodeExecutionStatusEvent,
    *,
    forward_notifications: bool = True,
) -> None:
    if not forward_notifications:
        return
    try:
        ws_forward_client = await shared_ws_forward.get()
        await ws_forward_client.send_message(
            event,
            user_id=payload.user_id,
            project_id=payload.project_id,
        )
    except Exception as e:
        logger.exception(f"Failed to send node status WS message: {e}")


async def _handle_node_metadata(
    payload: WorkerEventPayload,
    event: NodeMetadataEvent,
    *,
    forward_notifications: bool = True,
) -> None:
    if not forward_notifications:
        return
    try:
        ws_forward_client = await shared_ws_forward.get()
        await ws_forward_client.send_message(
            event,
            user_id=payload.user_id,
            project_id=payload.project_id,
        )
    except Exception as e:
        logger.exception(f"Failed to send node metadata WS message: {e}")
