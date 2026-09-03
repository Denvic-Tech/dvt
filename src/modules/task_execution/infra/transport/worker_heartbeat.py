from pydantic import BaseModel

from src.pipeline.execution_mode import PipelineExecutionMode
from src.schemas.http.system import SystemInfo


class HeartbeatPayload(BaseModel):
    """Worker heartbeat wire schema shared by producer and consumer."""

    worker_id: str
    capabilities: list[PipelineExecutionMode]
    max_concurrent: int
    timestamp: float | int
    active_task_id: str | None = None
    is_busy: bool | None = None
    available_slots: int | None = None
    system_info: SystemInfo | None = None
