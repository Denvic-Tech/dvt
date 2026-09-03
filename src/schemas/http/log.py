from typing import Optional
from datetime import datetime

from pydantic import BaseModel, Field


class LogEntrySchema(BaseModel):
    """
    Схема для передачи структурированной записи лога через WebSocket.
    """
    created_at: datetime = Field(description="Время создания записи")
    level: str = Field(description="Уровень лога (INFO, DEBUG, etc.)")
    service_name: str = Field(description="Имя сервиса, сгенерировавшего лог")
    message: str = Field(description="Текст сообщения")
    exception_traceback: Optional[str] = Field(
        None, description="Трассировка исключения, если есть")
    logger_name: Optional[str] = Field(None, description="Имя логгера (record.name)")
    module: Optional[str] = Field(None, description="Модуль, откуда пришёл лог")
    function: Optional[str] = Field(None, description="Функция")
    line: Optional[int] = Field(None, description="Номер строки")

    class Config:
        from_attributes = True


class LogEntriesPageSchema(BaseModel):
    items: list[LogEntrySchema] = Field(default_factory=list, description="Страница логов")
    total: int = Field(..., ge=0, description="Общее количество логов")
    limit: int = Field(..., ge=1, description="Размер страницы")
    offset: int = Field(..., ge=0, description="Смещение страницы")
    has_more: bool = Field(..., description="Есть ли следующая страница")
