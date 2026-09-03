from datetime import datetime
from enum import StrEnum
from typing import List, Optional

from pydantic import BaseModel

from src.enums import WorkerStatus


class SystemInfo(BaseModel):
    """
    Модель для хранения системной информации.
    """
    hostname: str

    os_type: str
    os_release: str
    os_version: str

    system_uptime_seconds: float
    app_uptime_seconds: float

    cpu_percent: float
    cpu_cores_physical: int
    cpu_cores_logical: int

    ram_total: float
    ram_available: float
    ram_used: float
    ram_used_percent: float

    disk_total: float
    disk_used: float
    disk_free: float
    disk_used_percent: float

    network_bytes_sent: int
    network_bytes_recv: int
    process_count: int


class WorkerSystemInfo(SystemInfo):
    worker_id: str
    status: WorkerStatus = WorkerStatus.ONLINE
    first_seen_at: Optional[float] = None
    last_heartbeat_at: Optional[float] = None
    last_heartbeat_received_at: Optional[float] = None
    last_status_change_at: Optional[float] = None
    offline_since: Optional[float] = None
    heartbeat_age_sec: Optional[float] = None
    has_running_task: bool = False
    running_task_ram_used: Optional[float] = None
    running_task_ram_used_percent: Optional[float] = None


class ServicesStatus(BaseModel):
    gateway: SystemInfo
    project_scheduler: Optional[SystemInfo]
    task_workers: Optional[List[WorkerSystemInfo]]


class VersionInfo(BaseModel):
    version: str


class RuntimeConfigFeatures(BaseModel):
    ai_analysis: bool


class RuntimeConfig(BaseModel):
    features: RuntimeConfigFeatures


class SystemStateValue(StrEnum):
    READY = "ready"
    UPDATING = "updating"
    DEGRADED = "degraded"


class SystemStateResponse(BaseModel):
    state: SystemStateValue
    retry_after_sec: int
    checked_at: datetime
