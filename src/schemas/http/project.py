from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pystructor import omit, partial

from src.modules.project.infra.db_models import ProjectRecord
from src.modules.task_execution.domain.types import TaskExecutionStatus
from src.schemas.http.project_variable import ProjectVariableBase


class ProjectLastRunSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    task_id: str = Field(..., description="ID запуска проекта")
    status: TaskExecutionStatus = Field(..., description="Статус запуска проекта")
    queued_at: datetime = Field(..., description="Время постановки запуска в очередь")
    started_at: datetime | None = Field(None, description="Время начала запуска проекта")
    finished_at: datetime | None = Field(None, description="Время завершения запуска проекта")
    message: str | None = Field(None, description="Краткое сообщение о результате запуска")
    termination_reason: str | None = Field(None, description="Причина аварийного завершения запуска")


@omit(ProjectRecord, "id", "created_at", "updated_at", "user_id", "user", "organization_id", "organization", "is_deleted")
class ProjectCreateSchema(BaseModel):
    """Схема для создания проекта в БД"""

    folder_id: str | None = Field(default=None, description="ID папки проекта")
    variables: dict[str, ProjectVariableBase] | None = Field(
        default=None,
        description="Typed-переменные проекта",
    )


@omit(ProjectRecord, "user_id")
class ProjectReadSchema(BaseModel):
    """Схема для чтения проекта с БД"""

    id: str = Field()
    folder_id: str | None = Field(default=None, description="ID папки проекта")
    user_email: str | None = Field(default=None, description="Email владельца проекта")
    variables: dict[str, ProjectVariableBase] | None = Field(
        default=None,
        description="Typed-переменные проекта",
    )
    last_runs: list[ProjectLastRunSchema] = Field(
        default_factory=list,
        description="Последние scheduler-запуски проекта",
    )

    class Config:
        from_attributes = True


@partial(ProjectCreateSchema)
class ProjectUpdateSchema(BaseModel):
    """Схема для обновления проекта в БД"""

    folder_id: str | None = Field(default=None, description="ID папки проекта")
    variables: dict[str, ProjectVariableBase] | None = Field(
        default=None,
        description="Typed-переменные проекта",
    )


class ProjectsDeleteSchema(BaseModel):
    """Схема для удаления проектов в БД"""

    project_ids: list[str] = Field(..., description="Список ID проектов для удаления")


class ProjectFolderCreateSchema(BaseModel):
    name: str = Field(..., min_length=1, description="Название папки проектов")
    parent_id: str | None = Field(default=None, description="ID родительской папки")


class ProjectFolderUpdateSchema(BaseModel):
    name: str | None = Field(default=None, min_length=1, description="Новое название папки проектов")
    parent_id: str | None = Field(default=None, description="Новый ID родительской папки")


class ProjectFolderReadSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., description="ID папки проектов")
    name: str = Field(..., description="Название папки проектов")
    parent_id: str | None = Field(default=None, description="ID родительской папки")
    user_id: str = Field(..., description="ID владельца папки")
    user_email: str | None = Field(default=None, description="Email владельца папки")
    organization_id: str = Field(..., description="ID организации")
    is_deleted: bool = Field(False, description="Удалена ли папка")
    created_at: datetime = Field(..., description="Дата создания")
    updated_at: datetime = Field(..., description="Дата обновления")


class ProjectFolderItemSchema(BaseModel):
    type: Literal["folder", "project"] = Field(..., description="Тип элемента")
    folder: ProjectFolderReadSchema | None = Field(default=None, description="Данные папки")
    project: ProjectReadSchema | None = Field(default=None, description="Данные проекта")


class ProjectItemsPageSchema(BaseModel):
    items: list[ProjectFolderItemSchema] = Field(default_factory=list, description="Элементы папки")
    total: int = Field(..., ge=0, description="Общее количество элементов")
    limit: int = Field(..., ge=1, description="Размер страницы")
    offset: int = Field(..., ge=0, description="Смещение страницы")
    has_more: bool = Field(..., description="Есть ли следующая страница")
    folder_id: str | None = Field(default=None, description="ID текущей папки")


class ProjectSearchPageSchema(BaseModel):
    items: list[ProjectFolderItemSchema] = Field(default_factory=list, description="Найденные папки и проекты")
    total: int = Field(..., ge=0, description="Общее количество найденных элементов")
    limit: int = Field(..., ge=1, description="Размер страницы")
    offset: int = Field(..., ge=0, description="Смещение страницы")
    has_more: bool = Field(..., description="Есть ли следующая страница")
