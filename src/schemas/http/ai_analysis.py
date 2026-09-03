from datetime import datetime

from pydantic import BaseModel, Field

from src.enums import AIAnalysisStatus
from src.schemas.http.ai_analysis_service import AIServiceAnalysisResultSchema


class AIAnalysisCreateSchema(BaseModel):
    task_id: str = Field(..., min_length=1)


class AIAnalysisCreateResponseSchema(BaseModel):
    request_id: str
    status: AIAnalysisStatus


class AIAnalysisReadSchema(BaseModel):
    request_id: str
    project_id: str
    status: AIAnalysisStatus
    title: str | None
    result: AIServiceAnalysisResultSchema | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class AIAnalysisHistoryItemSchema(BaseModel):
    request_id: str
    project_id: str
    task_id: str | None
    status: AIAnalysisStatus
    title: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None


class AIAnalysisHistoryResponseSchema(BaseModel):
    items: list[AIAnalysisHistoryItemSchema]
    total: int
    limit: int
    offset: int
