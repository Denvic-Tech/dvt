from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import Field, SQLModel


class LogRecord(SQLModel, table=True):
    __tablename__ = "logs"
    """
    Структура таблицы логов.

    id            - PK, авто-инкремент.
    created_at    - время создания.
    level         - INFO / DEBUG / ERROR …
    service_name  - имя сервиса (префикс), задаётся при старте.
    message       - текст сообщения.
    logger_name   - имя логгера (logger.name).
    module        - модуль, откуда пришёл лог.
    function      - функция.
    line          - номер строки.
    extra         - любые дополнительные данные (JSON).
    """

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(tz=UTC), nullable=False, index=True
    )
    level: str = Field(nullable=False, index=True)
    service_name: str = Field(nullable=False, index=True)
    message: str = Field(nullable=False)
    exception_traceback: str | None = Field(default=None, nullable=True)
    user_id: str | None = Field(default=None, foreign_key="users.id", index=True, nullable=True)
    task_id: str | None = Field(
        default=None,
        foreign_key="tasks.task_id",
        index=True,
        nullable=True,
    )
    logger_name: str | None = Field(default=None)
    module: str | None = Field(default=None)
    function: str | None = Field(default=None)
    line: int | None = Field(default=None)
