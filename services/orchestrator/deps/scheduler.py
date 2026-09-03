from services.orchestrator.scheduler import TaskScheduler
from services.orchestrator.deps.worker_registry import get_worker_registry


_scheduler: TaskScheduler | None = None


def init_task_scheduler() -> TaskScheduler:
    global _scheduler
    if _scheduler is None:
        registry = get_worker_registry()
        _scheduler = TaskScheduler(registry=registry)
    return _scheduler


def get_task_scheduler() -> TaskScheduler:
    if _scheduler is None:
        raise RuntimeError("TaskScheduler requested before initialization")
    return _scheduler
