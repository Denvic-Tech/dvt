import time

import orjson
from contracts.src.orchestrator.v1 import orchestrator_pb2, orchestrator_pb2_grpc

from services.orchestrator.deps.commands import accept_task_enqueue
from services.orchestrator.deps.execution_registry import get_task_execution_registry
from services.orchestrator.deps.scheduler import get_task_scheduler
from services.orchestrator.deps.worker_registry import get_worker_registry

from src import enums
from src.logger import logger
from src.modules.task_execution.domain.types import TaskTerminationReason
from src.schemas.http.system import WorkerSystemInfo
from src.schemas.internal import TaskInternal

import config


def _is_online_worker_status(status) -> bool:
    normalized_status = str(getattr(status, "value", status)).strip().lower()
    return normalized_status == str(enums.WorkerStatus.ONLINE).strip().lower()


class OrchestratorServicer(orchestrator_pb2_grpc.OrchestratorServicer):
    async def EnqueueTask(self, request, context):
        logger.debug(f"Task enqueue request: {request}")

        if not request.task_payload_json:
            logger.error("No task_payload_json provided, skipping")
            return orchestrator_pb2.EnqueueTaskResponse(
                accepted=False,
                error="task_payload_json is required",
            )

        try:
            task = TaskInternal.model_validate_json(request.task_payload_json)
        except Exception as exc:
            logger.warning("Failed to parse task payload", error=str(exc))
            return orchestrator_pb2.EnqueueTaskResponse(
                accepted=False,
                error=f"Invalid task payload: {exc}",
            )

        decision = await accept_task_enqueue(task)
        if not decision.accepted:
            return orchestrator_pb2.EnqueueTaskResponse(
                accepted=False,
                error=decision.error or "Failed to enqueue task",
            )

        return orchestrator_pb2.EnqueueTaskResponse(
            accepted=True,
            task_id=decision.task_id,
        )

    async def CancelTask(self, request, context):
        logger.debug(f"CancelTask request: {request}")

        if not request.task_id:
            logger.error("No task_id provided, skipping")
            return orchestrator_pb2.CancelTaskResponse(
                accepted=False,
                error="task_id is required",
            )

        scheduler = get_task_scheduler()
        try:
            await scheduler.handle_task_cancel(task_id=request.task_id)
        except Exception as exc:
            logger.exception("Failed to cancel task", task_id=request.task_id)
            return orchestrator_pb2.CancelTaskResponse(
                accepted=False,
                error=str(exc),
            )

        return orchestrator_pb2.CancelTaskResponse(accepted=True)

    async def ControlTask(self, request, context):
        logger.debug(f"ControlTask request: {request}")

        if not request.task_id:
            logger.error("No task_id provided, skipping")
            return orchestrator_pb2.TaskControlResponse(
                accepted=False,
                error="task_id is required",
            )

        if not request.command:
            return orchestrator_pb2.TaskControlResponse(
                accepted=False,
                error="command is required",
            )

        try:
            command = enums.TaskControlCommand(request.command)
        except ValueError:
            return orchestrator_pb2.TaskControlResponse(
                accepted=False,
                error=f"Unknown command: {request.command}",
            )

        if command in (enums.TaskControlCommand.STOP, enums.TaskControlCommand.HARD_STOP):
            scheduler = get_task_scheduler()
            try:
                if command == enums.TaskControlCommand.STOP:
                    await scheduler.request_task_stop(
                        task_id=request.task_id,
                        reason=TaskTerminationReason.USER_STOP.value,
                    )
                else:
                    await scheduler.request_task_hard_stop(
                        task_id=request.task_id,
                        reason=TaskTerminationReason.USER_HARD_STOP.value,
                    )
            except Exception as exc:
                logger.exception("Failed to handle task control", task_id=request.task_id)
                return orchestrator_pb2.TaskControlResponse(
                    accepted=False,
                    error=str(exc),
                )

            return orchestrator_pb2.TaskControlResponse(accepted=True)

        return orchestrator_pb2.TaskControlResponse(
            accepted=False,
            error=f"Unsupported command: {request.command}",
        )

    async def GetSystemStats(self, request, context):
        logger.debug(f"GetSystemStats request: {request}")

        now_ts = time.time()
        worker_registry = get_worker_registry()
        execution_registry = get_task_execution_registry()

        executions_by_worker_id = {}
        for execution in await execution_registry.all():
            if execution.is_stale(
                now_ts,
                config.ORCHESTRATOR.ORCHESTRATOR_EXECUTION_TELEMETRY_STALE_TIMEOUT_SEC,
            ):
                continue
            executions_by_worker_id[execution.worker_id] = execution

        workers = sorted(
            worker_registry.all(),
            key=lambda worker: (
                0 if _is_online_worker_status(worker.status) else 1,
                -float(worker.last_received_at),
            ),
        )

        system_infos = []
        for worker in workers:
            if worker.system_info is None:
                continue

            execution = executions_by_worker_id.get(worker.worker_id)
            worker_info = WorkerSystemInfo.model_validate({
                **worker.system_info.model_dump(),
                "worker_id": worker.worker_id,
                "status": worker.status,
                "first_seen_at": float(worker.first_seen_at),
                "last_heartbeat_at": float(worker.timestamp),
                "last_heartbeat_received_at": float(worker.last_received_at),
                "last_status_change_at": float(worker.last_status_change_at),
                "offline_since": (
                    float(worker.offline_since) if worker.offline_since is not None else None
                ),
                "heartbeat_age_sec": max(float(now_ts) - float(worker.last_received_at), 0.0),
            })

            if execution is not None:
                worker_info.has_running_task = True
                worker_info.running_task_ram_used = float(execution.rss_bytes)
                worker_info.running_task_ram_used_percent = (
                    (float(execution.rss_bytes) / float(worker_info.ram_total)) * 100.0
                    if worker_info.ram_total > 0
                    else None
                )

            system_infos.append(worker_info)

        payload = [WorkerSystemInfo.model_validate(info).model_dump() for info in system_infos]
        return orchestrator_pb2.GetSystemStatsResponse(
            system_infos_json=orjson.dumps(payload).decode("utf-8"),
            content_type="application/json",
        )

    async def GetExecutionCapacity(self, request, context):
        logger.debug(f"GetExecutionCapacity request: {request}")

        now_ts = time.time()
        worker_registry = get_worker_registry()
        workers = worker_registry.all()

        alive_workers = [
            worker
            for worker in workers
            if worker.is_alive(now_ts, config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC)
        ]
        total_capacity = sum(
            max(int(worker.max_concurrent), 0)
            for worker in alive_workers
            if _is_online_worker_status(worker.status)
        )
        execution_registry = get_task_execution_registry()
        active_worker_ids = {
            record.worker_id
            for record in await execution_registry.all()
            if not record.is_stale(
                now_ts, config.ORCHESTRATOR.ORCHESTRATOR_EXECUTION_TELEMETRY_STALE_TIMEOUT_SEC
            )
        }
        def _worker_available_slots(worker) -> int:
            capacity = max(int(worker.max_concurrent), 0)
            if not (
                worker.is_alive(now_ts, config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC)
                and _is_online_worker_status(worker.status)
            ):
                return 0
            if getattr(worker, "availability_reported", False):
                return min(max(int(worker.available_slots), 0), capacity)
            return 0 if worker.worker_id in active_worker_ids or getattr(worker, "is_busy", False) else capacity

        busy_capacity = sum(
            max(int(worker.max_concurrent), 0) - _worker_available_slots(worker)
            for worker in alive_workers
            if _is_online_worker_status(worker.status)
        )
        available_capacity = sum(
            _worker_available_slots(worker)
            for worker in alive_workers
            if _is_online_worker_status(worker.status)
        )

        payload = [
            orchestrator_pb2.WorkerCapacityInfo(
                worker_id=worker.worker_id,
                max_concurrent=max(int(worker.max_concurrent), 0),
                status=str(worker.status),
                alive=worker.is_alive(
                    now_ts,
                    config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC,
                ),
                capabilities=[str(capability) for capability in sorted(worker.capabilities, key=str)],
                busy=(
                    worker.is_alive(
                        now_ts,
                        config.ORCHESTRATOR.ORCHESTRATOR_HEARTBEAT_TIMEOUT_SEC,
                    )
                    and _is_online_worker_status(worker.status)
                    and _worker_available_slots(worker) < max(int(worker.max_concurrent), 0)
                ),
                available_slots=_worker_available_slots(worker),
            )
            for worker in workers
        ]
        return orchestrator_pb2.GetExecutionCapacityResponse(
            alive_workers_count=len(alive_workers),
            total_capacity=total_capacity,
            busy_capacity=busy_capacity,
            available_capacity=available_capacity,
            workers=payload,
        )
