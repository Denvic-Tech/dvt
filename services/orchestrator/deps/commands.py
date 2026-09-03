import time
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from services.orchestrator.celery_app import celery_app
from services.orchestrator.deps.worker_registry import get_worker_registry
from services.orchestrator.task_finalizer import publish_task_terminal_event

from src import enums
from src.logger import logger
from src.modules.task_execution.domain.types import TaskExecutionStatus, TaskTerminationReason
from src.modules.task_execution.facade import build_task_execution_facade
from src.modules.task_execution.infra.transport import NestedTaskEnqueueCommand, TaskInternal
from src.pipeline.execution_mode import PipelineExecutionMode


def _is_online_worker_status(status) -> bool:
    normalized_status = str(getattr(status, "value", status)).strip().lower()
    return normalized_status == str(enums.WorkerStatus.ONLINE).strip().lower()


@dataclass(slots=True)
class TaskEnqueueDecision:
    accepted: bool
    task_id: str
    should_schedule: bool
    error: str | None = None


async def accept_task_enqueue(task: TaskInternal) -> TaskEnqueueDecision:
    log = logger.bind(
        component="orchestrator.enqueue",
        task_id=task.task_id,
        project_id=task.project_id,
    )

    try:
        enqueue_result = await build_task_execution_facade(celery_app=celery_app).enqueue_task_internal(task)
        execution = enqueue_result.execution
    except IntegrityError as exc:
        log.warning("IntegrityError on durable enqueue", error=str(exc))
        return TaskEnqueueDecision(False, task.task_id, False, str(exc))

    for superseded in enqueue_result.superseded:
        await publish_task_terminal_event(
            task_id=superseded.task_id,
            user_id=superseded.user_id,
            project_id=superseded.project_id,
            mode=PipelineExecutionMode(superseded.mode),
            status=TaskExecutionStatus.CANCELLED,
        )

    should_schedule = execution.status == TaskExecutionStatus.QUEUED
    log.info(
        "Task persisted with durable dispatch",
        status=execution.status,
        superseded_task_ids=[item.task_id for item in enqueue_result.superseded],
    )

    return TaskEnqueueDecision(
        accepted=True,
        task_id=task.task_id,
        should_schedule=should_schedule,
    )


async def handle_nested_task_enqueue(command: NestedTaskEnqueueCommand) -> None:
    log = logger.bind(
        component="orchestrator.command.nested_enqueue",
        request_id=command.request_id,
        task_id=command.task.task_id,
        origin_worker_id=command.origin_worker_id,
    )

    execution = build_task_execution_facade(celery_app=celery_app)
    reservation_created = False
    if command.wait_for_completion:
        registry = get_worker_registry()
        alive_worker_ids = [
            worker.worker_id
            for worker in registry.get_alive_workers(time.time())
            if _is_online_worker_status(worker.status)
        ]
        reservation = await execution.reserve_nested_wait.execute(
            parent_task_id=command.parent_task_id,
            child_task_id=command.task.task_id,
            origin_worker_id=command.origin_worker_id,
            alive_worker_ids=alive_worker_ids,
        )
        if not reservation.accepted:
            error_message = reservation.error or "Nested wait reservation was rejected."
            log.warning(error_message)
            failed = await execution.fail_pending_execution.execute(
                task_id=command.task.task_id,
                termination_reason=TaskTerminationReason.NESTED_WAIT_CAPACITY_LOST,
                message=error_message,
            )
            if failed is None:
                raise RuntimeError(
                    f"Failed to reject pending nested execution task_id={command.task.task_id}"
                )
            await publish_task_terminal_event(
                task_id=failed.task_id,
                user_id=failed.user_id,
                project_id=failed.project_id,
                mode=PipelineExecutionMode(failed.mode),
                status=TaskExecutionStatus.ERROR,
                error_message=error_message,
            )
            return
        reservation_created = True

    decision = await accept_task_enqueue(command.task)
    if not decision.accepted:
        if reservation_created:
            await execution.release_nested_wait.execute(parent_task_id=command.parent_task_id)
        raise RuntimeError(decision.error or "Failed to enqueue nested task")
