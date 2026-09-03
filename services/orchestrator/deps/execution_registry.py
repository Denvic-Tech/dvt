from functools import lru_cache

from services.orchestrator.execution_registry import TaskExecutionRegistry


@lru_cache(maxsize=1)
def get_task_execution_registry() -> TaskExecutionRegistry:
    return TaskExecutionRegistry()
