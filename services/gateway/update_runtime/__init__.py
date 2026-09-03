from functools import lru_cache

import config

from .client import InstallationManagerClient
from .monitor import ServiceReadinessChecker, SystemStateMonitor


@lru_cache
def get_installation_manager_client() -> InstallationManagerClient:
    return InstallationManagerClient(
        base_url=config.INSTALLATION_MANAGER.INSTALLATION_MANAGER_URL,
        request_timeout_sec=config.INSTALLATION_MANAGER.REQUEST_TIMEOUT_SEC,
        summary_timeout_sec=config.SYSTEM_STATE.STATUS_REQUEST_TIMEOUT_SEC,
    )


@lru_cache
def get_system_state_monitor() -> SystemStateMonitor:
    return SystemStateMonitor(
        manager_client=get_installation_manager_client(),
        readiness_checker=ServiceReadinessChecker(),
        poll_interval_sec=config.SYSTEM_STATE.POLL_INTERVAL_SEC,
        retry_after_sec=config.SYSTEM_STATE.RETRY_AFTER_SEC,
        manager_stale_timeout_sec=config.SYSTEM_STATE.MANAGER_STALE_TIMEOUT_SEC,
        readiness_timeout_sec=config.SYSTEM_STATE.READINESS_TIMEOUT_SEC,
        recent_update_window_sec=config.SYSTEM_STATE.RECENT_UPDATE_WINDOW_SEC,
        readiness_probe_timeout_sec=config.SYSTEM_STATE.STATUS_REQUEST_TIMEOUT_SEC,
    )


__all__ = [
    "get_installation_manager_client",
    "get_system_state_monitor",
]
