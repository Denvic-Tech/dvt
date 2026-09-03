from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, UniqueConstraint
from sqlmodel import Field, SQLModel

from src.models.mixins import TimestampedModel


class ProjectRecord(TimestampedModel, SQLModel, table=True):
    __tablename__ = "projects"

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    name: str = Field(nullable=True, description="Name of the project", index=True)

    user_id: str = Field(foreign_key="users.id", nullable=False,
                         description="ID пользователя, которому принадлежит проект")
    organization_id: str = Field(
        foreign_key="organizations.id",
        nullable=False,
        index=True,
        description="ID организации, которой принадлежит проект",
    )
    is_deleted: bool = Field(default=False, description="Flag indicating if the project is deleted")

    folder_id: str | None = Field(
        default=None,
        foreign_key="project_folders.id",
        nullable=True,
        index=True,
        description="ID папки, в которой находится проект",
    )

    store_enabled: bool | None = Field(default=False, nullable=True, description='Включен ли кеш данных для этого проекта')

    dirty_node_ids: list[str] = Field(
        default_factory=list,
        sa_type=JSON,
        nullable=False,
        description="Ноды, измененные после последнего успешного полного запуска",
    )
    graph_revision: int = Field(
        default=0,
        nullable=False,
        description="Ревизия вычислительной части графа",
        ge=0,
    )

    ttl_time: int | None = Field(
        default=0,
        nullable=True,
        description='Время жизни кеша данных в секундах',
        ge=0
    )

    workers_count: int | None = Field(
        default=0,
        nullable=True,
        description='Количество потоков для подключений',
        ge=0
    )

    # Исправленное поле variables
    variables: dict | None = Field(
        default=None,
        sa_type=JSON,
        nullable=True,
        description="Переменные проекта"
    )

    __table_args__ = (
        UniqueConstraint('id', 'organization_id', name='unique_project_id_organization_id'),
        CheckConstraint('ttl_time >= 0', name='check_ttl_time_non_negative'),
        CheckConstraint('workers_count >= 0', name='check_workers_count_non_negative'),
        CheckConstraint('graph_revision >= 0', name='check_graph_revision_non_negative'),
    )
