from pydantic import BaseModel, Field


class UpdateRequestSchema(BaseModel):
    version: str = Field(min_length=1, description="Target DVT version")


class UpdateResponseSchema(BaseModel):
    success: bool = True
    message: str
    version: str
    job_id: str | None = None


class UpdateStepSchema(BaseModel):
    id: str
    title: str
    status: str
    detail: str = ""


class UpdateStatusSchema(BaseModel):
    id: str
    kind: str
    state: str
    error: str | None = None
    version: str = ""
    started_at: str
    finished_at: str | None = None
    steps: list[UpdateStepSchema]
    log: list[str]
    log_total: int
