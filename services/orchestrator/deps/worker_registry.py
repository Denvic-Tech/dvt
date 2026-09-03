from functools import lru_cache

from services.orchestrator.worker_registry import WorkerRegistry


@lru_cache(maxsize=1)
def get_worker_registry() -> WorkerRegistry:
    """Get the global WorkerRegistry instance."""
    registry = WorkerRegistry()
    return registry
