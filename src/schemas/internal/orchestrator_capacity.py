from pydantic import BaseModel, Field

from src.enums import WorkerStatus
from src.pipeline.execution_mode import PipelineExecutionMode


class WorkerCapacitySnapshot(BaseModel):
    worker_id: str
    max_concurrent: int = Field(ge=0)
    status: WorkerStatus
    alive: bool
    capabilities: list[PipelineExecutionMode] = Field(default_factory=list)
    busy: bool = False
    available_slots: int = Field(default=0, ge=0)


class ExecutionCapacitySnapshot(BaseModel):
    alive_workers_count: int = Field(ge=0)
    total_capacity: int = Field(ge=0)
    busy_capacity: int = Field(default=0, ge=0)
    available_capacity: int = Field(default=0, ge=0)
    workers: list[WorkerCapacitySnapshot] = Field(default_factory=list)
