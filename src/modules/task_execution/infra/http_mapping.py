from .http_schemas import TaskInfo
from .queries.tasks import TaskReadModel


def task_read_to_info(task: TaskReadModel) -> TaskInfo:
    return TaskInfo(
        task_id=task.task_id,
        status=task.status,
        started_at=task.started_at,
        message=task.message,
        source=task.source,
    )
