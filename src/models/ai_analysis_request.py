from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, Enum as SAEnum, ForeignKey, Index, String, Text
from sqlmodel import Field, SQLModel

from src.enums import AIAnalysisStatus

from .mixins import TimestampedModel


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class AIAnalysisRequestRecord(TimestampedModel, SQLModel, table=True):
    __tablename__ = "ai_analysis_requests"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    task_id: str = Field(sa_column=Column(String, nullable=False, index=True))
    ai_service_request_id: str | None = Field(
        default=None,
        sa_column=Column(String, nullable=True, index=True),
    )
    project_id: str = Field(
        sa_column=Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    )
    user_id: str = Field(sa_column=Column(String, ForeignKey("users.id"), nullable=False, index=True))
    organization_id: str = Field(
        sa_column=Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    )
    status: AIAnalysisStatus = Field(
        default=AIAnalysisStatus.QUEUED,
        sa_column=Column(
            SAEnum(
                AIAnalysisStatus,
                name="ai_analysis_status",
                native_enum=False,
                values_callable=lambda enum_cls: [item.value for item in enum_cls],
            ),
            nullable=False,
            default=AIAnalysisStatus.QUEUED,
        ),
    )
    title: str | None = Field(default=None, sa_column=Column(String(40), nullable=True))
    context: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    result: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    __table_args__ = (
        Index(
            "ix_ai_analysis_requests_project_user_status_created",
            "project_id",
            "user_id",
            "status",
            "created_at",
        ),
        Index(
            "ix_ai_analysis_requests_org_status_created",
            "organization_id",
            "status",
            "created_at",
        ),
        Index("ix_ai_analysis_requests_project_created", "project_id", "created_at"),
    )
