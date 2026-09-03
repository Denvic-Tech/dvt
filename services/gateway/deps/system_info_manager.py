from src.managers.system_info_manager import SystemInfoManager
from src.schemas.http.system import SystemInfo

system_info_manager = SystemInfoManager()


def get_sys_info() -> SystemInfo:
    return system_info_manager.get_system_info()
