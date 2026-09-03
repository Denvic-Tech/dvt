from typing import Literal

from pydantic import Field

from .base import EventBase
from .types import EventType


class TaskExecutionTelemetryEvent(EventBase):
    type: Literal[EventType.TASK_EXECUTION_TELEMETRY] = EventType.TASK_EXECUTION_TELEMETRY

    task_id: str = Field(description="ID of the task, for which the telemetry is reported")
    hostname: str = Field(description="Hostname, on which the task process is running")
    pid: int = Field(description="PID of the process that is executing the task")
    rss_bytes: int = Field(description="Resident set size of the executing task process")
    memory_limit_bytes: int | None = Field(
        default=None,
        description="Effective memory limit of the worker execution environment",
    )
    system_ram_used_percent: float = Field(description="Current RAM pressure on the host/container")
