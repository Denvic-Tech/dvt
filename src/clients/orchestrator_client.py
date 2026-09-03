import json
from collections.abc import Iterable
from typing import TYPE_CHECKING

import grpc
import orjson
from contracts.src.orchestrator.v1 import orchestrator_pb2, orchestrator_pb2_grpc
from loguru import logger

from src.clients.base.grpc import BaseGrpcClient, ChannelOption
from src.enums import WorkerStatus
from src.exception_registry import RegisteredHTTPException
from src.exception_registry.exception_types import ExceptionCategory
from src.modules.task_execution.domain.types import TaskControlCommand
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.system import WorkerSystemInfo
from src.schemas.internal.orchestrator_capacity import (
    ExecutionCapacitySnapshot,
    WorkerCapacitySnapshot,
)

import config

if TYPE_CHECKING:
    from src.schemas.internal import TaskInternal


class OrchestratorRPCError(RegisteredHTTPException):
    name = "ORCHESTRATOR_RPC_ERROR"
    code = "ORCHESTRATOR_503"
    description = "Orchestrator RPC error"
    category = ExceptionCategory.ORCHESTRATOR_CLIENT.value


class OrchestratorTaskRejected(OrchestratorRPCError):
    name = "ORCHESTRATOR_TASK_REJECTED"
    code = "ORCHESTRATOR_500"
    description = "Orchestrator rejected task"
    category = ExceptionCategory.ORCHESTRATOR_CLIENT.value


class OrchestratorInvalidStats(OrchestratorRPCError):
    name = "ORCHESTRATOR_INVALID_STATS"
    code = "ORCHESTRATOR_500"
    description = "Orchestrator invalid stats"
    category = ExceptionCategory.ORCHESTRATOR_CLIENT.value


def _orchestrator_service_config(timeout_seconds: float) -> str:
    cfg = {
        "methodConfig": [
            {
                "name": [{"service": "orchestrator.v1.Orchestrator"}],
                "timeout": f"{timeout_seconds}s",
                "retryPolicy": {
                    "maxAttempts": 3,
                    "initialBackoff": "0.1s",
                    "maxBackoff": "0.6s",
                    "backoffMultiplier": 2.0,
                    "retryableStatusCodes": ["UNAVAILABLE"],
                },
            }
        ]
    }
    return json.dumps(cfg)


def _orchestrator_channel_options(timeout_seconds: float) -> tuple[ChannelOption, ...]:
    return (
        ("grpc.service_config", _orchestrator_service_config(timeout_seconds)),
        ("grpc.enable_http_proxy", 0),
        ("grpc.max_send_message_length", 10 * 1024 * 1024),
        ("grpc.max_receive_message_length", 10 * 1024 * 1024),
        ("grpc.keepalive_time_ms", 10 * 60 * 60 * 1000),
        ("grpc.keepalive_timeout_ms", 10 * 60 * 60 * 1000),
        ("grpc.http2.min_time_between_pings_ms", 60 * 1000),
        ("grpc.http2.max_pings_without_data", 0),
    )


class GrpcOrchestratorClient(BaseGrpcClient[orchestrator_pb2_grpc.OrchestratorStub]):
    def __init__(
        self,
        target: str,
        *,
        token: str | None = None,
        secure: bool = False,
        ssl_credentials: grpc.ChannelCredentials | None = None,
        channel: grpc.aio.Channel | None = None,
        channel_options: Iterable[tuple[str, int]] | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        super().__init__(
            target=target,
            token=token,
            secure=secure,
            ssl_credentials=ssl_credentials,
            channel=channel,
            channel_options=channel_options,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def default_target() -> str:
        return f"{config.ORCHESTRATOR.ORCHESTRATOR_HOST}:{config.ORCHESTRATOR.ORCHESTRATOR_PORT}"

    def _default_channel_options(self) -> Iterable[ChannelOption]:
        return _orchestrator_channel_options(self._timeout_seconds)

    def _create_stub(self, channel: grpc.aio.Channel) -> orchestrator_pb2_grpc.OrchestratorStub:
        return orchestrator_pb2_grpc.OrchestratorStub(channel)

    async def enqueue_task(self, task: "TaskInternal") -> str:
        stub = self._ensure_stub()
        try:
            resp = await stub.EnqueueTask(
                orchestrator_pb2.EnqueueTaskRequest(
                    task_payload_json=task.model_dump_json(),
                    content_type="application/json",
                ),
                metadata=self.metadata(),
            )
        except grpc.aio.AioRpcError as exc:
            logger.error(f"GrpcOrchestratorClient.enqueue_task error: {exc}")
            raise OrchestratorRPCError(status_code=503, detail=exc.details()) from exc

        if not resp.accepted:
            detail = resp.error or "Orchestrator rejected task"
            raise OrchestratorTaskRejected(status_code=503, detail=detail)

        return resp.task_id or task.task_id

    async def cancel_task(self, task_id: str) -> None:
        stub = self._ensure_stub()
        try:
            resp = await stub.CancelTask(
                orchestrator_pb2.CancelTaskRequest(task_id=task_id),
                metadata=self.metadata(),
            )
        except grpc.aio.AioRpcError as exc:
            logger.error(f"GrpcOrchestratorClient.cancel_task error: {exc}")
            raise OrchestratorRPCError(status_code=503, detail=exc.details()) from exc

        if not resp.accepted:
            detail = resp.error or "Orchestrator rejected cancel request"
            raise OrchestratorTaskRejected(status_code=503, detail=detail)

    async def control_task(self, task_id: str, command: TaskControlCommand | str) -> None:
        stub = self._ensure_stub()
        command_value = command.value if isinstance(command, TaskControlCommand) else str(command)
        try:
            resp = await stub.ControlTask(
                orchestrator_pb2.TaskControlMessage(
                    task_id=task_id,
                    command=command_value,
                ),
                metadata=self.metadata(),
            )
        except grpc.aio.AioRpcError as exc:
            logger.error(f"GrpcOrchestratorClient.control_task error: {exc}")
            raise OrchestratorRPCError(status_code=503, detail=exc.details()) from exc

        if not resp.accepted:
            detail = resp.error or "Orchestrator rejected control request"
            raise OrchestratorTaskRejected(status_code=503, detail=detail)

    async def get_system_stats(self) -> list[WorkerSystemInfo]:
        stub = self._ensure_stub()
        try:
            resp = await stub.GetSystemStats(
                orchestrator_pb2.GetSystemStatsRequest(),
                metadata=self.metadata(),
            )
        except grpc.aio.AioRpcError as exc:
            logger.error(f"GrpcOrchestratorClient.get_system_stats error: {exc}")
            raise OrchestratorRPCError(status_code=503, detail=exc.details()) from exc

        if not resp.system_infos_json:
            return []

        try:
            items = orjson.loads(resp.system_infos_json)
        except orjson.JSONDecodeError as exc:
            raise OrchestratorInvalidStats(
                status_code=500, detail=f"Invalid stats JSON: {exc}"
            ) from exc

        if not isinstance(items, list):
            raise OrchestratorInvalidStats(
                status_code=500, detail="Invalid stats payload format"
            )

        return [WorkerSystemInfo(**item) for item in items]

    async def get_execution_capacity(self) -> ExecutionCapacitySnapshot:
        stub = self._ensure_stub()
        try:
            resp = await stub.GetExecutionCapacity(
                orchestrator_pb2.GetExecutionCapacityRequest(),
                metadata=self.metadata(),
            )
        except grpc.aio.AioRpcError as exc:
            logger.error(f"GrpcOrchestratorClient.get_execution_capacity error: {exc}")
            raise OrchestratorRPCError(status_code=503, detail=exc.details()) from exc

        workers = [
            WorkerCapacitySnapshot(
                worker_id=item.worker_id,
                max_concurrent=int(item.max_concurrent),
                status=WorkerStatus(item.status),
                alive=bool(item.alive),
                capabilities=[PipelineExecutionMode(value) for value in item.capabilities],
                busy=bool(item.busy),
                available_slots=int(item.available_slots),
            )
            for item in resp.workers
        ]
        return ExecutionCapacitySnapshot(
            alive_workers_count=int(resp.alive_workers_count),
            total_capacity=int(resp.total_capacity),
            busy_capacity=int(resp.busy_capacity),
            available_capacity=int(resp.available_capacity),
            workers=workers,
        )
