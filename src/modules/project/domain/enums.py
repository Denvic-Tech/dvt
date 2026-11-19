from enum import StrEnum
from typing import Literal

# Dask shuffle method for a project's pipeline runs. A project without one (``None``) uses the
# installation default: whatever Dask resolves on its own, normally ``disk``.
ShuffleMethod = Literal["disk", "tasks"]


class ProjectScheduleRunStatus(StrEnum):
    PENDING = "PENDING"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    WAITING_RETRY = "WAITING_RETRY"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"
