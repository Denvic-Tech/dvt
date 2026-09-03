from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.internal import TaskInternal

from ..domain.entities import TaskExecution
from ..domain.types import TaskExecutionStatus, TaskSource


def task_internal_to_execution(task: TaskInternal) -> TaskExecution:
    return TaskExecution(
        task_id=task.task_id,
        user_id=task.user_id,
        organization_id=task.organization_id,
        project_id=task.project_id,
        mode=PipelineExecutionMode(task.mode),
        source=TaskSource(task.source),
        status=TaskExecutionStatus.PENDING,
        force_exec=task.force_exec,
        queued_at=task.queued_at,
        schedule_run_id=task.schedule_run_id,
        schedule_attempt=task.schedule_attempt,
    )
