from dataclasses import dataclass

from src.enums import WorkerStatus
from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.system import SystemInfo


@dataclass(slots=True)
class WorkerState:
    """Mutable in-memory Orchestrator runtime state; not a transport schema."""

    worker_id: str
    timestamp: float
    first_seen_at: float
    last_received_at: float
    last_status_change_at: float
    capabilities: set[PipelineExecutionMode]
    max_concurrent: int
    status: WorkerStatus
    offline_since: float | None = None
    active_task_id: str | None = None
    is_busy: bool = False
    available_slots: int = 0
    availability_reported: bool = False
    system_info: SystemInfo | None = None

    def is_alive(self, now_ts: float, heartbeat_timeout_sec: int) -> bool:
        return (
            self.status == WorkerStatus.ONLINE
            and now_ts - self.last_received_at < heartbeat_timeout_sec
        )
