from functools import lru_cache

from src.managers.background_scheduler import BackgroundSchedulerManager


@lru_cache(maxsize=1)
def get_background_scheduler_manager() -> BackgroundSchedulerManager:
    return BackgroundSchedulerManager()
