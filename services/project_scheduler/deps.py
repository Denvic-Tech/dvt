from functools import lru_cache

from src.managers.project_scheduler import ProjectSchedulerManager
from src.managers.system_info_manager import SystemInfoManager
from src.schemas.http.system import SystemInfo


@lru_cache(maxsize=1)
def get_project_scheduler_manager():
    return ProjectSchedulerManager()


system_info_manager = SystemInfoManager()


def get_sys_info() -> SystemInfo:
    return system_info_manager.get_system_info()
