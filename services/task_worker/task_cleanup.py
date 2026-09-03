"""Task-scoped runtime cleanup for persistent Celery children."""

import asyncio
import gc
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import Any

from src.logger import logger

CleanupCallback = Callable[[], Awaitable[None] | None]
_BACKGROUND_TASK_CANCEL_TIMEOUT_SEC = 2.0


def _partd_roots() -> tuple[Path, ...]:
    roots = {Path(tempfile.gettempdir())}
    posix_tmp = Path("/tmp")
    if posix_tmp.exists():
        roots.add(posix_tmp)
    return tuple(roots)


def cleanup_tmp_partd_artifacts(tmp_dir: Path | None = None) -> None:
    roots = (tmp_dir,) if tmp_dir is not None else _partd_roots()

    # (operation, exception type, errno, message) -> [count, sample_paths]
    errors: dict[tuple[str, str, int | None, str], list] = defaultdict(
        lambda: [0, []]
    )

    max_samples = 3

    def record_error(operation: str, path: Path, exc: OSError) -> None:
        key = (
            operation,
            type(exc).__name__,
            exc.errno,
            exc.strerror or str(exc),
        )

        entry = errors[key]
        entry[0] += 1

        if len(entry[1]) < max_samples:
            entry[1].append(str(path))

    for root in roots:
        try:
            artifact_paths = list(root.glob("*.partd"))
        except OSError as exc:
            record_error("list", root, exc)
            continue

        for artifact_path in artifact_paths:
            try:
                if artifact_path.is_dir() and not artifact_path.is_symlink():
                    shutil.rmtree(artifact_path)
                else:
                    artifact_path.unlink(missing_ok=True)
            except FileNotFoundError:
                # Artifact disappeared between discovery and removal.
                continue
            except OSError as exc:
                record_error("remove", artifact_path, exc)

    if errors:
        lines = ["Failed to cleanup some task worker temp partd artifacts:"]

        for (operation, exc_type, errno, message), (count, paths) in errors.items():
            errno_text = f", errno={errno}" if errno is not None else ""

            lines.append(
                f"- {operation}: {count} failure(s): "
                f"{exc_type}{errno_text}: {message}"
            )

            for path in paths:
                lines.append(f"    example: {path}")

            if count > len(paths):
                lines.append(f"    ... and {count - len(paths)} more")

        logger.warning("\n".join(lines))


def release_pipeline_processor_references(processor: Any | None) -> None:
    """Drop task-owned graphs/dataframes/futures retained by PipelineProcessor.

    The shared extension/Node DSL registries and process-scoped stores are not
    touched. Assigning new containers (rather than clearing the original ones)
    avoids mutating the TaskInternal pipeline snapshot by alias.
    """
    if processor is None:
        return

    for attr in (
        "nodes_outputs",
        "nodes_output_hashes",
        "nodes_metadata",
        "node_signal_states",
    ):
        if hasattr(processor, attr):
            setattr(processor, attr, {})

    for attr in (
        "executed_nodes",
        "failed_nodes",
        "skipped_nodes",
        "restored_nodes",
    ):
        if hasattr(processor, attr):
            setattr(processor, attr, [])

    for attr in ("_completed_node_ids", "_recoverable_failed_node_ids"):
        if hasattr(processor, attr):
            setattr(processor, attr, set())

    for attr in (
        "_execution_order",
        "_planned_execution_order",
        "_affected_metadata_nodes",
        "stop_event",
    ):
        if hasattr(processor, attr):
            setattr(processor, attr, None)

    # Break the largest task-local reference chains without mutating TaskInternal.
    if hasattr(processor, "pipeline"):
        processor.pipeline = {}
    if hasattr(processor, "task"):
        processor.task = None


class TaskExecutionCleanup:
    """Releases resources owned by one pipeline execution, never shared runtime."""

    def __init__(
        self,
        *,
        background_task_cancel_timeout_sec: float = _BACKGROUND_TASK_CANCEL_TIMEOUT_SEC,
    ) -> None:
        self._background_task_cancel_timeout_sec = max(
            float(background_task_cancel_timeout_sec),
            0.0,
        )

    async def execute(
        self,
        *,
        background_tasks: Iterable[asyncio.Task[Any]] = (),
        processor: Any | None = None,
        callbacks: Iterable[CleanupCallback] = (),
    ) -> None:
        tasks = tuple(background_tasks)
        for task in tasks:
            task.cancel()

        done: set[asyncio.Task[Any]] = set()
        pending: set[asyncio.Task[Any]] = set()
        if tasks:
            done, pending = await asyncio.wait(
                tasks,
                timeout=self._background_task_cancel_timeout_sec,
            )

        for task in done:
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Task-scoped background resource failed during cleanup")

        for task in pending:
            logger.warning(
                "Task-scoped background resource did not stop before cleanup deadline",
                background_task_name=task.get_name(),
                timeout_sec=self._background_task_cancel_timeout_sec,
            )
            # Request cancellation again in case the coroutine swallowed the first
            # CancelledError. Do not let an auxiliary transport task block the
            # authoritative DB terminal transition indefinitely.
            task.cancel()

        for callback in callbacks:
            try:
                result = callback()
                if result is not None:
                    await result
            except Exception:
                logger.exception("Task-scoped cleanup callback failed")

        release_pipeline_processor_references(processor)
        cleanup_tmp_partd_artifacts()
        gc.collect()
