from datetime import datetime
from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, Enum as SAEnum, ForeignKey, Index, String, text
from sqlmodel import Field, SQLModel

from src.enums import RetryBackoff
from src.models.mixins import TimestampedModel
from src.pipeline.execution_mode import PipelineExecutionMode

from ...domain import ProjectScheduleRunStatus


class ProjectScheduleRunRecord(TimestampedModel, SQLModel, table=True):
    __tablename__ = "project_schedule_runs"

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    schedule_id: str = Field(
        sa_column=Column(
            String,
            ForeignKey("project_schedules.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    status: ProjectScheduleRunStatus = Field(
        default=ProjectScheduleRunStatus.PENDING,
        sa_column=Column(
            SAEnum(ProjectScheduleRunStatus, name="project_schedule_run_status", native_enum=False),
            nullable=False,
            default=ProjectScheduleRunStatus.PENDING,
        ),
    )
    scheduled_at: datetime = Field(nullable=False)
    attempt_number: int = Field(default=0, nullable=False, ge=0)
    attempt_started_at: datetime | None = Field(default=None, nullable=True)
    current_task_id: str | None = Field(default=None, nullable=True, index=True)
    next_retry_at: datetime | None = Field(default=None, nullable=True, index=True)
    last_error: str | None = Field(default=None, nullable=True)
    finished_at: datetime | None = Field(default=None, nullable=True)

    max_retries: int = Field(default=0, nullable=False, ge=0, le=10)
    retry_delay_seconds: int = Field(default=60, nullable=False, ge=1, le=86400)
    retry_backoff: RetryBackoff = Field(
        default=RetryBackoff.FIXED,
        sa_column=Column(
            SAEnum(RetryBackoff, name="project_schedule_retry_backoff", native_enum=False),
            nullable=False,
            default=RetryBackoff.FIXED,
        ),
    )
    retry_max_delay_seconds: int = Field(default=3600, nullable=False, ge=1, le=86400)
    mode: PipelineExecutionMode = Field(
        default=PipelineExecutionMode.FULL,
        sa_column=Column(
            SAEnum(PipelineExecutionMode, name="project_schedule_exec_mode", native_enum=False),
            nullable=False,
            default=PipelineExecutionMode.FULL,
        ),
    )
    force_exec: bool = Field(default=False, nullable=False)
    scheduled_by_user_id: str | None = Field(default=None, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "attempt_number >= 0",
            name="check_project_schedule_runs_attempt",
        ),
        CheckConstraint(
            "max_retries BETWEEN 0 AND 10",
            name="check_project_schedule_runs_max_retries",
        ),
        CheckConstraint(
            "retry_delay_seconds BETWEEN 1 AND 86400",
            name="check_project_schedule_runs_retry_delay",
        ),
        CheckConstraint(
            "retry_max_delay_seconds BETWEEN 1 AND 86400",
            name="check_project_schedule_runs_retry_max_delay",
        ),
        Index(
            "ix_project_schedule_runs_reconcile",
            "status",
            "next_retry_at",
        ),
        Index(
            "uq_project_schedule_runs_active_schedule",
            "schedule_id",
            unique=True,
            postgresql_where=text("finished_at IS NULL"),
            sqlite_where=text("finished_at IS NULL"),
        ),
    )
