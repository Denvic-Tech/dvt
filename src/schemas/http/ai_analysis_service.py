from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AIServiceAnalysisType(StrEnum):
    LOG_ERROR = "log_error"


class AIServiceAnalysisStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


class AIServiceAnalysisClassification(StrEnum):
    USER_PIPELINE_ERROR = "user_pipeline_error"
    DVT_BUG = "dvt_bug"
    INFRA_ERROR = "infra_error"
    UNKNOWN = "unknown"


class AIServiceAnalysisSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AIServiceAnalysisTaskSchema(StrictSchema):
    id: str
    status: str
    mode: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AIServiceAnalysisProjectSchema(StrictSchema):
    id: str
    name: str | None = None


class AIServicePipelineNodeContextSchema(StrictSchema):
    id: str
    name: str | None = None
    type: str
    input_values: dict[str, Any] = Field(default_factory=dict)
    upstream_node_ids: list[str] = Field(default_factory=list)
    source_module: str
    source_file: str | None = None


class AIServicePipelineEdgeContextSchema(StrictSchema):
    source_node_id: str
    target_node_id: str
    source_output: str | None = None
    target_input: str | None = None


class AIServicePipelineContextSchema(StrictSchema):
    nodes: list[AIServicePipelineNodeContextSchema] = Field(min_length=1)
    edges: list[AIServicePipelineEdgeContextSchema] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_pipeline_context(self) -> "AIServicePipelineContextSchema":
        seen_node_ids: set[str] = set()

        for node in self.nodes:
            if node.id in seen_node_ids:
                raise ValueError(f"Duplicate pipeline node id: {node.id}")
            seen_node_ids.add(node.id)

        for edge in self.edges:
            if edge.source_node_id not in seen_node_ids:
                raise ValueError(f"Pipeline edge source is not present in nodes: {edge.source_node_id}")
            if edge.target_node_id not in seen_node_ids:
                raise ValueError(f"Pipeline edge target is not present in nodes: {edge.target_node_id}")

        return self

    def iter_upstream_nodes(self) -> list[AIServicePipelineNodeContextSchema]:
        return [node for node in self.nodes]


class AIServiceLogEntrySchema(StrictSchema):
    timestamp: datetime | None = None
    level: str
    service: str | None = None
    module: str | None = None
    function: str | None = None
    line: int | None = None
    message: str


class AIServiceRecommendedActionSchema(StrictSchema):
    title: str
    description: str


class AIServiceSourceContextItemSchema(StrictSchema):
    path: str
    source: str
    snippet: str | None = None


class AIServiceAnalysisResultSchema(StrictSchema):
    title: str = Field(min_length=1, max_length=40)
    classification: AIServiceAnalysisClassification
    severity: AIServiceAnalysisSeverity
    summary: str
    details: str
    recommended_actions: list[AIServiceRecommendedActionSchema] = Field(default_factory=list)
    bug_report_suggested: bool = False
    matched_pattern: str | None = None
    source_context_used: list[AIServiceSourceContextItemSchema] = Field(default_factory=list)


class AIServiceAnalysisContextSchema(StrictSchema):
    traceback_source_modules: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_traceback_source_modules(self) -> "AIServiceAnalysisContextSchema":
        normalized_items: list[str] = []
        seen: set[str] = set()
        for item in self.traceback_source_modules:
            normalized = item.strip()
            if not normalized:
                raise ValueError("analysis_context.traceback_source_modules must not contain empty values")
            lowered = normalized.lower()
            if lowered in seen:
                raise ValueError(f"Duplicate traceback source module: {normalized}")
            seen.add(lowered)
            normalized_items.append(normalized)
        self.traceback_source_modules = normalized_items
        return self


class AIServiceLogErrorAnalysisCreateSchema(StrictSchema):
    idempotency_key: str | None = None
    dvt_version: str
    task: AIServiceAnalysisTaskSchema
    project: AIServiceAnalysisProjectSchema
    pipeline_context: AIServicePipelineContextSchema
    analysis_context: AIServiceAnalysisContextSchema
    logs: list[AIServiceLogEntrySchema] = Field(default_factory=list)
    traceback: str | None = None

    def iter_upstream_nodes(self) -> list[AIServicePipelineNodeContextSchema]:
        return self.pipeline_context.iter_upstream_nodes()


class AIServiceLogErrorAnalysisCreateResponseSchema(StrictSchema):
    request_id: str
    status: AIServiceAnalysisStatus


class AIServiceAnalysisRequestReadSchema(StrictSchema):
    request_id: str
    status: AIServiceAnalysisStatus
    analysis_type: AIServiceAnalysisType
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: AIServiceAnalysisResultSchema | None = None
    error: str | None = None


class AIServiceAnalysisRequestBatchItemSchema(StrictSchema):
    request_id: str
    found: bool
    request: AIServiceAnalysisRequestReadSchema | None = None


class AIServiceAnalysisRequestBatchReadSchema(StrictSchema):
    items: list[AIServiceAnalysisRequestBatchItemSchema] = Field(default_factory=list)
