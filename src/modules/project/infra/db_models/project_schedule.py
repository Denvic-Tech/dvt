from uuid import uuid4

from sqlalchemy import CheckConstraint, Column, Enum as SAEnum
from sqlmodel import Field, SQLModel

from src.enums import RetryBackoff
from src.models.mixins import TimestampedModel
from src.pipeline.execution_mode import PipelineExecutionMode


class ProjectScheduleRecord(TimestampedModel, SQLModel, table=True):
    __tablename__ = "project_schedules"

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(
        foreign_key="projects.id",
        nullable=False,
        unique=True,
        index=True,
        description="ID проекта, для которого хранится расписание",
    )
    scheduled_by_user_id: str | None = Field(
        default=None,
        foreign_key="users.id",
        nullable=True,
        index=True,
        description="ID пользователя, который последним сохранил расписание",
    )
    cron: str = Field(nullable=False, description="CRON выражение для запуска проекта")
    disabled: bool = Field(default=False, nullable=False, description="Отключено ли расписание")
    mode: PipelineExecutionMode = Field(
        default=PipelineExecutionMode.FULL,
        sa_column=Column(
            SAEnum(PipelineExecutionMode, name="project_schedule_exec_mode", native_enum=False),
            nullable=False,
            default=PipelineExecutionMode.FULL,
        ),
    )
    force_exec: bool = Field(default=False, nullable=False)
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

    __table_args__ = (
        CheckConstraint(
            "max_retries BETWEEN 0 AND 10",
            name="check_project_schedules_max_retries",
        ),
        CheckConstraint(
            "retry_delay_seconds BETWEEN 1 AND 86400",
            name="check_project_schedules_retry_delay",
        ),
        CheckConstraint(
            "retry_max_delay_seconds BETWEEN 1 AND 86400",
            name="check_project_schedules_retry_max_delay",
        ),
    )
