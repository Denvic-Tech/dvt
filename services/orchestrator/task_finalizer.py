from services.orchestrator.celery_app import celery_app
from services.orchestrator.deps.execution_registry import get_task_execution_registry
from services.orchestrator.deps.worker_registry import get_worker_registry

from src import enums
from src.logger import logger
from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.modules.task_execution.facade import build_task_execution_facade
from src.pipeline.execution_mode import PipelineExecutionMode
from src.runtime.async_runtime import shared_ws_forward
from src.schemas.event import TaskError, TaskExecutionStatusEvent


async def publish_task_terminal_event(
    *,
    task_id: str,
    user_id: str,
    project_id: str,
    mode: PipelineExecutionMode,
    status: TaskExecutionStatus,
    error_message: str | None = None,
) -> None:
    event = TaskExecutionStatusEvent(
        task_id=task_id,
        mode=mode,
        status=status,
        error=TaskError(message=error_message) if error_message is not None else None,
    )
    try:
        ws_forward_client = await shared_ws_forward.get()
        await ws_forward_client.send_message(
            event,
            user_id=user_id,
            project_id=project_id,
        )
    except Exception as exc:
        logger.exception(
            "Failed to send terminal task WS message",
            task_id=task_id,
            status=status,
            error=str(exc),
        )


async def finalize_task_terminal_status(
    *,
    task_id: str,
    user_id: str,
    project_id: str,
    worker_id: str | None,
    mode: PipelineExecutionMode,
    status: TaskExecutionStatus,
    termination_reason: str | None = None,
    error_message: str | None = None,
) -> bool:
    if status not in (
        TaskExecutionStatus.ERROR,
        TaskExecutionStatus.CANCELLED,
    ):
        raise ValueError(f"Unsupported terminal task status: {status}")

    if termination_reason is None:
        raise ValueError("Reconciliation finalization requires termination_reason")

    execution = build_task_execution_facade(celery_app=celery_app)
    finalized_task = await execution.finalize_reconciled.execute(
        task_id=task_id,
        termination_reason=termination_reason,
        message=error_message,
    )
    if finalized_task is None or finalized_task.status != status.value:
        logger.info(
            "Skipping terminal task finalization due to lifecycle mismatch",
            task_id=task_id,
            status=status,
            termination_reason=termination_reason,
        )
        return False

    # The PostgreSQL commit above is authoritative. Everything below is
    # ephemeral cleanup/notification and must not invalidate terminalization.
    try:
        registry = get_task_execution_registry()
        await registry.remove(task_id)
    except Exception as exc:
        logger.warning(
            "Failed to cleanup execution telemetry after terminal DB commit",
            task_id=task_id,
            error=str(exc),
        )

    if worker_id is not None:
        try:
            get_worker_registry().mark_idle(worker_id=worker_id, task_id=task_id)
        except Exception as exc:
            logger.warning(
                "Failed to mark worker idle after terminal DB commit",
                task_id=task_id,
                worker_id=worker_id,
                error=str(exc),
            )

    try:
        await execution.release_nested_wait.execute(
            parent_task_id=task_id,
            child_task_id=task_id,
            worker_id=worker_id,
        )
    except Exception as exc:
        logger.warning(
            "Failed to cleanup nested wait after terminal DB commit",
            task_id=task_id,
            worker_id=worker_id,
            error=str(exc),
        )

    await publish_task_terminal_event(
        task_id=task_id,
        user_id=user_id,
        project_id=project_id,
        mode=mode,
        status=status,
        error_message=error_message,
    )
    return True
