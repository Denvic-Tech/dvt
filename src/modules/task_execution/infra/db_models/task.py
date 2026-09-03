from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlmodel import Field, SQLModel

from src.pipeline.execution_mode import PipelineExecutionMode

from ...domain.types import TaskExecutionStatus, TaskSource


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class TaskRecord(SQLModel, table=True):
    __tablename__ = "tasks"

    task_id: str = Field(sa_column=Column(String, primary_key=True))
    mode: PipelineExecutionMode = Field(
        sa_column=Column(
            SAEnum(PipelineExecutionMode, name="task_queue_exec_mode", native_enum=False),
            nullable=False,
        )
    )
    force_exec: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, default=False),
    )
    status: TaskExecutionStatus = Field(
        default=TaskExecutionStatus.PENDING,
        sa_column=Column(
            SAEnum(TaskExecutionStatus, name="task_queue_status", native_enum=False),
            nullable=False,
            default=TaskExecutionStatus.PENDING,
        ),
    )
    termination_reason: str | None = Field(
        default=None,
        sa_column=Column(String, nullable=True),
    )
    source: TaskSource = Field(
        default=TaskSource.API,
        sa_column=Column(String, nullable=False, default=TaskSource.API),
    )
    message: str | None = Field(default=None)
    assigned_worker_id: str | None = Field(
        default=None,
        sa_column=Column(String, nullable=True),
    )

    queued_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, default=_utcnow),
    )
    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    finished_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    updated_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            default=_utcnow,
            onupdate=_utcnow,
        ),
    )

    # Cross-context references remain plain FK columns. Relationships belong to
    # the read/query side, not to the authoritative task lifecycle aggregate.
    user_id: str = Field(
        sa_column=Column(String, ForeignKey("users.id"), nullable=False, index=True)
    )
    organization_id: str = Field(
        sa_column=Column(String, ForeignKey("organizations.id"), nullable=False, index=True)
    )
    project_id: str = Field(
        sa_column=Column(String, ForeignKey("projects.id"), nullable=False, index=True)
    )
    schedule_run_id: str | None = Field(
        default=None,
        sa_column=Column(
            String,
            ForeignKey("project_schedule_runs.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    schedule_attempt: int | None = Field(default=None, nullable=True, ge=1)

    __table_args__ = (
        UniqueConstraint(
            "schedule_run_id",
            "schedule_attempt",
            name="uq_tasks_schedule_run_attempt",
        ),
        CheckConstraint(
            "schedule_attempt IS NULL OR schedule_attempt >= 1",
            name="check_tasks_schedule_attempt_positive",
        ),
    )

    class Config:
        arbitrary_types_allowed = True
