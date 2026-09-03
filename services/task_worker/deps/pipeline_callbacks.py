import asyncio
import time
import threading

import orjson
import redis.asyncio as redis

from services.task_worker.helpers import get_worker_id
from src.modules.task_execution.domain.types import TaskExecutionStatus

from src.node_dsl import BaseNode, types
from src.node_dsl.types import NodeMetadata
from src.schemas.internal import TaskInternal
from src.schemas.event import (
    TaskExecutionStatusEvent,
    TaskExecutionTelemetryEvent,
    NodeExecutionStatusEvent,
    NodeMetadataEvent,
    TaskError
)
from src.schemas.worker_event_payload import WorkerEventPayload
from src import enums, types
import config


_redis_clients_by_loop: dict[asyncio.AbstractEventLoop, redis.Redis] = {}
_default_redis_client: redis.Redis | None = None
_redis_lock = threading.RLock()


def _build_redis_client() -> redis.Redis:
    return redis.from_url(config.CELERY.CELERY_BROKER_URL)


async def _close_clients(clients: list[redis.Redis]) -> None:
    for client in clients:
        try:
            await client.aclose()
        except Exception:
            continue


async def _cleanup_closed_loop_clients() -> None:
    stale_clients: list[redis.Redis] = []
    with _redis_lock:
        for loop, client in list(_redis_clients_by_loop.items()):
            if loop.is_closed():
                _redis_clients_by_loop.pop(loop, None)
                stale_clients.append(client)
    if stale_clients:
        await _close_clients(stale_clients)


async def get_redis() -> redis.Redis:
    await _cleanup_closed_loop_clients()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        with _redis_lock:
            client = _default_redis_client
        if client is not None:
            return client

        new_client = _build_redis_client()
        with _redis_lock:
            existing = _default_redis_client
            if existing is None:
                _default_redis_client = new_client
                return new_client

        await _close_clients([new_client])
        assert existing is not None
        return existing

    with _redis_lock:
        client = _redis_clients_by_loop.get(loop)
    if client is not None:
        return client

    new_client = _build_redis_client()
    with _redis_lock:
        existing = _redis_clients_by_loop.get(loop)
        if existing is None:
            _redis_clients_by_loop[loop] = new_client
            return new_client

    await _close_clients([new_client])
    assert existing is not None
    return existing


async def close_redis_clients() -> None:
    global _default_redis_client

    with _redis_lock:
        clients = list(_redis_clients_by_loop.values())
        _redis_clients_by_loop.clear()
        if _default_redis_client is not None:
            clients.append(_default_redis_client)
            _default_redis_client = None

    if not clients:
        return

    unique_clients: list[redis.Redis] = []
    seen: set[int] = set()
    for client in clients:
        client_id = id(client)
        if client_id in seen:
            continue
        seen.add(client_id)
        unique_clients.append(client)

    await _close_clients(unique_clients)


async def send_event(payload: WorkerEventPayload) -> None:
    # TODO: Вариант 3 — вынести отправку событий в отдельный dispatcher с asyncio.Queue.
    # TODO: Вариант 3 — добавить retry/backoff и метрики очереди (enqueue/drop/latency).
    # TODO: Вариант 3 — ввести backpressure policy при перегрузке Redis или очереди.
    event = {
        "worker_id": get_worker_id(),
        "timestamp": int(time.time()),
        "payload": orjson.dumps(payload.model_dump()),
    }
    redis_client = await get_redis()
    await redis_client.xadd(
        config.ORCHESTRATOR.ORCH_EVENTS_STREAM,
        event,
        maxlen=config.ORCHESTRATOR.ORCH_EVENTS_MAXLEN,
        approximate=True,
    )


async def on_task_started(task: "TaskInternal"):
    await send_event(WorkerEventPayload(
        user_id=task.user_id,
        project_id=task.project_id,
        task_id=task.task_id,
        worker_id=get_worker_id(),

        event=TaskExecutionStatusEvent(
            task_id=task.task_id,
            mode=task.mode,
            status=TaskExecutionStatus.STARTED,
        )
    ))


async def on_task_running(task: "TaskInternal"):
    await send_event(WorkerEventPayload(
        user_id=task.user_id,
        project_id=task.project_id,
        task_id=task.task_id,
        worker_id=get_worker_id(),

        event=TaskExecutionStatusEvent(
            task_id=task.task_id,
            mode=task.mode,
            status=TaskExecutionStatus.RUNNING,
        )
    ))


async def on_task_success(task: "TaskInternal"):
    await send_event(WorkerEventPayload(
        user_id=task.user_id,
        project_id=task.project_id,
        task_id=task.task_id,
        worker_id=get_worker_id(),

        event=TaskExecutionStatusEvent(
            task_id=task.task_id,
            mode=task.mode,
            status=TaskExecutionStatus.SUCCESS,
        )
    ))


async def on_task_error(task: "TaskInternal", message: str):
    await send_event(WorkerEventPayload(
        user_id=task.user_id,
        project_id=task.project_id,
        task_id=task.task_id,
        worker_id=get_worker_id(),

        event=TaskExecutionStatusEvent(
            task_id=task.task_id,
            mode=task.mode,
            status=TaskExecutionStatus.ERROR,
            error=TaskError(message=message),
        )
    ))


async def on_task_canceled(task: "TaskInternal"):
    await send_event(WorkerEventPayload(
        user_id=task.user_id,
        project_id=task.project_id,
        task_id=task.task_id,
        worker_id=get_worker_id(),

        event=TaskExecutionStatusEvent(
            task_id=task.task_id,
            mode=task.mode,
            status=TaskExecutionStatus.CANCELLED,
        )
    ))


async def send_task_execution_telemetry(
        task: "TaskInternal",
        *,
        hostname: str,
        pid: int,
        rss_bytes: int,
        memory_limit_bytes: int | None,
        system_ram_used_percent: float,
):
    await send_event(WorkerEventPayload(
        user_id=task.user_id,
        project_id=task.project_id,
        task_id=task.task_id,
        worker_id=get_worker_id(),

        event=TaskExecutionTelemetryEvent(
            task_id=task.task_id,
            hostname=hostname,
            pid=pid,
            rss_bytes=rss_bytes,
            memory_limit_bytes=memory_limit_bytes,
            system_ram_used_percent=system_ram_used_percent,
        )
    ))


async def on_node_started(
        user_id: str,
        project_id: str,
        task_id: str,
        node: "BaseNode",
):
    await send_event(WorkerEventPayload(
        user_id=user_id,
        project_id=project_id,
        task_id=task_id,
        worker_id=get_worker_id(),

        event=NodeExecutionStatusEvent(
            task_id=task_id,
            node_id=node._node_id,
            status=enums.ExecutionStatus.RUNNING,
            execution_mode=node.execution_mode,
        )
    ))


async def on_node_success(
        user_id: str,
        project_id: str,
        task_id: str,
        node: "BaseNode",
):
    await send_event(WorkerEventPayload(
        user_id=user_id,
        project_id=project_id,
        task_id=task_id,
        worker_id=get_worker_id(),

        event=NodeExecutionStatusEvent(
            task_id=task_id,
            node_id=node._node_id,
            status=enums.ExecutionStatus.SUCCESS,
            execution_mode=node.execution_mode,
        )
    ))


async def on_node_error(
        user_id: str,
        project_id: str,
        task_id: str,
        node: "BaseNode",
        message: str,
):
    await send_event(WorkerEventPayload(
        user_id=user_id,
        project_id=project_id,
        task_id=task_id,
        worker_id=get_worker_id(),

        event=NodeExecutionStatusEvent(
            task_id=task_id,
            node_id=node._node_id,
            status=enums.ExecutionStatus.ERROR,
            execution_mode=node.execution_mode,
            message=message,
        )
    ))


async def on_node_metadata(
        user_id: str,
        project_id: str,
        task_id: str,
        node: "BaseNode",
        metadata: "NodeMetadata",
):
    await send_event(WorkerEventPayload(
        user_id=user_id,
        project_id=project_id,
        task_id=task_id,
        worker_id=get_worker_id(),

        event=NodeMetadataEvent(
            project_id=project_id,
            task_id=task_id,
            node_id=node._node_id,
            metadata=metadata,
        )
    ))
