from datetime import datetime
from typing import Optional, Dict, List

from pydantic import BaseModel, Field


class DCCConnector(BaseModel):
    id_connector: Optional[str] = Field(None, description="Сквозной идентификатор сессии обмена сообщениями между ЦУМ и Коннекторами")
    type: str = Field(..., description="Тип коннектора. Передается при создании")
    name: str = Field(..., description='Название коннектора')
    group_name: Optional[str] = Field(None, description='Группа коннектора')
    user_name: Optional[str] = Field(None, description='Имя пользователя создавшего коннектор')
    timestamp: Optional[datetime] = Field(None, description='дата/время сообщения')
    data: Optional[Dict] = Field(None, description='JSON с версией коннектора, ID лицензии и тд.')
    info: Optional[str] = Field(None, description='JSON с доп версией из коннектора.')
    last_status: Optional[str] = Field(None, description="Статус")
    last_status_dt: Optional[datetime] = Field(None, description="Время последнего статуса")
    previous_status: Optional[str] = Field(None, description="Предпоследний статус")
    previous_status_dt: Optional[datetime] = Field(None, description="Время предпоследнего статуса")
    ecc_dt: Optional[datetime] = Field(None, description='Дата вставки/обновления')
    is_deleted: Optional[bool] = Field(False, description='Удален')


class DCCConnectorsListPage(BaseModel):
    limit: int
    offset: int
    count: int
    data: List[DCCConnector] = Field(default=[])


class DCCProject(BaseModel):
    id_connector: str = Field(..., description="ID коннектора. Выдается при регистрации")
    id_project: str = Field(..., description="внутренний уникальный Guid проекта (задачи) в Коннекторе")
    name: Optional[str] = Field(None, description="Название проекта")
    timestamp: Optional[datetime] = Field(None, description="Дата сообщения")
    version: Optional[str] = Field(None, description="Версия проекта")
    type: Optional[str] = Field(None, description="Тип проекта")
    project_path: Optional[str] = Field(None, description="Путь проекта")
    parent_id_project: Optional[str] = Field(None, description="Parent id проекта")
    last_status: Optional[str] = Field(None, description="Статус")
    last_status_dt: Optional[datetime] = Field(None, description="Время последнего статуса")
    previous_status: Optional[str] = Field(None, description="Предпоследний статус")
    previous_status_dt: Optional[datetime] = Field(None, description="Время предпоследнего статуса")
    ecc_dt: Optional[datetime] = Field(None, description="Дата вставки/обновления")
    is_deleted: Optional[bool] = Field(False, description="Удален")


class DCCTask(BaseModel):
    id_task: str = Field(..., description="Уникальный ID задачи")
    id_connector: str = Field(..., description="ID коннектора. Выдается при регистрации")
    id_project: Optional[str] = Field(None, description="Внутренний уникальный Guid проекта (задачи) в Коннекторе")
    parent_id_project: Optional[str] = Field(None, description="Parent id проекта")
    command_type: Optional[str] = Field(
        None, description="Тип задачи. Варианты: exec, loadTemplate, reload"
    )
    timestamp: Optional[datetime] = Field(None, description="Дата сообщения")
    status: Optional[str] = Field(None, description="Статус")
    data: Optional[Dict] = Field(None, description="JSON")
    status_info: Optional[str] = Field(None, description="Доп инфа по статусу")
    source: Optional[str] = Field(None, description="Источник задачи")
    created_by: Optional[str] = Field(None, description="Логин создавшего пользователя")
    updated_by: Optional[str] = Field(None, description="Логин обновившего задачу пользователя")
    ecc_dt: Optional[datetime] = Field(None, description="Дата вставки/обновления")
    is_deleted: Optional[bool] = Field(False, description="Удален")


class DCCTaskLog(BaseModel):
    """
    Pydantic-модель для отправки на /add_log
    """
    id_connector: str
    id_project: Optional[str] = None
    id_task: str = Field(..., description="Произвольный ID задачи (зависит от вашей логики)")
    id_line: str = Field(..., description="Идентификатор строки в проекте (например module:line)")
    data: dict
    segment: Optional[str] = None
    count: Optional[int] = None
    timestamp: datetime
