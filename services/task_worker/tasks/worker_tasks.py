import asyncio

from services.task_worker.celery_app import (
    celery_app,
    ensure_extension_runtime_for_task_process,
    ensure_log_sinks_for_task_process,
    finalize_task_process_logging,
)
from services.task_worker.deps.pipeline_callbacks import (
    on_task_canceled,
    on_task_error,
    on_task_success,
)
from services.task_worker.deps.pipeline_processor import get_pipeline_processor
from services.task_worker.execution_slot import mark_execution_slot_busy, mark_execution_slot_idle
from services.task_worker.helpers import get_async_runner, get_worker_id
from services.task_worker.task_cleanup import TaskExecutionCleanup, cleanup_tmp_partd_artifacts
from services.task_worker.telemetry import run_task_telemetry_loop

from src.crud import project as project_crud
from src.db import AsyncSessionLocal
from src.logger import logger
from src.managers.extension_dependency_manager import ExtensionDependencyManager
from src.modules.app_settings.public import helpers as app_settings_helpers
from src.modules.task_execution.domain.policies import terminal_status_for_termination_reason
from src.modules.task_execution.domain.types import TaskTerminationReason
from src.modules.task_execution.facade import build_task_execution_facade
from src.node_dsl import ExecutionSettings
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.internal import TaskInternal

import config


def _run_in_loop(coro):
    return get_async_runner().run(coro)


def _handle_task_payload(task_payload: TaskInternal | dict) -> None:
    ensure_log_sinks_for_task_process()
    task = _coerce_task(task_payload)
    worker_id = get_worker_id()
    execution = build_task_execution_facade(celery_app=celery_app)
    context = {
        "user_id": task.user_id,
        "task_id": task.task_id,
        "project_id": task.project_id,
        "send_ws_messages": task.send_ws_messages,
    }
    log = logger.bind(**context)

    async def _emit_terminal(status: str, message: str | None = None) -> None:
        try:
            if status == "SUCCESS":
                await on_task_success(task)
            elif status == "CANCELLED":
                await on_task_canceled(task)
            elif status == "ERROR":
                await on_task_error(task, message or "Task execution failed")
        except Exception:
            log.exception("Failed to publish terminal task event after DB finalization")

    async def _mark_success() -> bool:
        with logger.contextualize(**context):
            if not await execution.finalize_task.execute(
                task_id=task.task_id,
                worker_id=worker_id,
                status="SUCCESS",
            ):
                return False
            async with AsyncSessionLocal() as session:
                if (
                    task.mode == PipelineExecutionMode.FULL
                    and task.changed_node_ids
                    and task.graph_revision is not None
                ):
                    await project_crud.clear_project_graph_dirty_if_revision(
                        session,
                        project_id=task.project_id,
                        graph_revision=task.graph_revision,
                        node_ids=task.changed_node_ids,
                    )
                await session.commit()
            await _emit_terminal("SUCCESS")
            return True

    async def _mark_error(message: str) -> bool:
        with logger.contextualize(**context):
            finalized = await execution.finalize_task.execute(
                task_id=task.task_id,
                worker_id=worker_id,
                status="ERROR",
                message=message,
            )
            if finalized:
                await _emit_terminal("ERROR", message)
            return finalized

    async def _mark_cancelled(reason: str) -> bool:
        with logger.contextualize(**context):
            finalized = await execution.finalize_task.execute(
                task_id=task.task_id,
                worker_id=worker_id,
                status="CANCELLED",
                termination_reason=reason,
            )
            if finalized:
                await _emit_terminal("CANCELLED")
            return finalized

    async def _prepare_task() -> bool:
        with logger.contextualize(**context):
            return await execution.claim_task.execute(
                task_id=task.task_id,
                worker_id=worker_id,
            )

    async def _current_cancellation_reason() -> str | None:
        return await execution.cancellation.get_stop_reason(task_id=task.task_id)

    slot_owned = False
    with logger.contextualize(**context):
        try:
            if not _run_in_loop(_prepare_task()):
                log.info(f"Skipping non-claimable task ID={task.task_id}")
                return

            mark_execution_slot_busy(task.task_id)
            slot_owned = True

            # Claim first so runtime/readiness failures have an authoritative
            # worker owner and can be persisted as ERROR. Pipeline execution
            # still cannot begin until the required extension revision is loaded.
            ensure_extension_runtime_for_task_process(
                set(getattr(task, "extension_names", None) or ())
            )

            async def _run_task():
                with logger.contextualize(**context):
                    app_settings = await app_settings_helpers.get_app_settings()
                    execution_settings = ExecutionSettings.from_app_runtime_settings(
                        app_settings.runtime
                    )
                    if not await execution.mark_task_running.execute(
                        task_id=task.task_id,
                        worker_id=worker_id,
                    ):
                        return None, await _current_cancellation_reason()

                    stop_event = asyncio.Event()
                    cancellation_reason: dict[str, str | None] = {"value": None}

                    async def _watch_cancellation() -> None:
                        cancellation_reason["value"] = await execution.cancellation.wait_for_stop(
                            task_id=task.task_id
                        )
                        stop_event.set()

                    telemetry_task = asyncio.create_task(
                        run_task_telemetry_loop(task),
                        name=f"task-telemetry-{task.task_id}",
                    )
                    cancellation_watcher = asyncio.create_task(
                        _watch_cancellation(),
                        name=f"task-cancellation-{task.task_id}",
                    )
                    processor = None
                    try:
                        processor = get_pipeline_processor(
                            task=task,
                            stop_event=stop_event,
                            execution_settings=execution_settings,
                        )
                        result = await processor.process()
                        # Close the race where STOP commits after the last node but
                        # before the watcher has observed the notification/poll.
                        if cancellation_reason["value"] is None:
                            cancellation_reason["value"] = await _current_cancellation_reason()
                        return result, cancellation_reason["value"]
                    finally:
                        await TaskExecutionCleanup().execute(
                            background_tasks=(telemetry_task, cancellation_watcher),
                            processor=processor,
                        )

            result, cancellation_reason = _run_in_loop(_run_task())
            if cancellation_reason is not None:
                terminal_status = terminal_status_for_termination_reason(cancellation_reason)
                if terminal_status == "ERROR":
                    _run_in_loop(_mark_error(f"Task terminated: {cancellation_reason}"))
                    log.warning(
                        f"Task ID={task.task_id} terminated with failure reason={cancellation_reason}"
                    )
                else:
                    _run_in_loop(_mark_cancelled(cancellation_reason))
                    log.info(f"Task ID={task.task_id} cancelled cooperatively")
                return

            if result is None:
                log.info(f"Skipping task whose RUNNING transition was rejected ID={task.task_id}")
                return

            if result.success:
                if _run_in_loop(_mark_success()):
                    log.success(f"Task ID={task.task_id} done successfully")
                    return

                # SUCCESS is intentionally rejected from CANCEL_REQUESTED. Re-read
                # PostgreSQL so a STOP racing with finalization becomes CANCELLED.
                late_reason = _run_in_loop(_current_cancellation_reason())
                if late_reason is not None and _run_in_loop(_mark_cancelled(late_reason)):
                    log.info(f"Task ID={task.task_id} cancelled during success finalization")
                    return
                log.warning(f"Task ID={task.task_id} terminal SUCCESS transition was rejected")
                return

            error_message = result.error_message or "Task processing finished unsuccessfully"
            _run_in_loop(_mark_error(error_message))
            log.error(f"Task ID={task.task_id} done unsuccessfully")

        except Exception as exc:
            try:
                reason = _run_in_loop(_current_cancellation_reason())
                if reason in {
                    TaskTerminationReason.USER_STOP.value,
                    TaskTerminationReason.USER_HARD_STOP.value,
                }:
                    _run_in_loop(_mark_cancelled(reason))
                else:
                    _run_in_loop(_mark_error(str(exc)))
            except Exception:
                log.exception("Failed to persist task terminal state in DB")
            log.exception("Task crashed in celery worker")
        finally:
            if slot_owned:
                mark_execution_slot_idle(task_id=task.task_id)


def _run_with_new_loop(coro):
    return asyncio.run(coro)


def _coerce_task(payload: TaskInternal | dict) -> TaskInternal:
    if isinstance(payload, TaskInternal):
        return payload
    return TaskInternal.model_validate(payload)


@celery_app.task(name="task_worker.handle_task", queue=config.CELERY.CELERY_TASKS_QUEUE)
def handle_task(task_payload: TaskInternal | dict) -> None:
    try:
        _handle_task_payload(task_payload)
    finally:
        # Safety net for failures before the task-scoped cleanup object is created.
        cleanup_tmp_partd_artifacts()
        finalize_task_process_logging()


@celery_app.task(name="task_worker.install_extension_deps", queue=config.CELERY.CELERY_DEPS_QUEUE)
def install_extension_deps(payload: dict) -> None:
    """Install dependencies for one extension in the one-slot worker container."""
    ensure_log_sinks_for_task_process()
    extension_name = (payload or {}).get("extension_name")
    log = logger.bind(extension_name=extension_name)

    if not extension_name:
        log.error("Missing extension_name in payload")
        finalize_task_process_logging()
        return

    try:
        dependency_manager = ExtensionDependencyManager()
        result = _run_with_new_loop(dependency_manager.install_dependencies(extension_name))
        if result.success:
            log.info(f"Extension dependencies installed count={result.dependencies_count}")
        else:
            log.error(f"Extension dependencies installation failed error={result.error_message}")
    except Exception:
        log.exception("Failed to install extension dependencies")
        raise
    finally:
        finalize_task_process_logging()
