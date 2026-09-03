from pydantic import BaseModel, Field

from .event import Event


class WorkerEventPayload(BaseModel):
    user_id: str = Field(..., description=f"ID пользователя")
    project_id: str = Field(..., description=f"ID проекта")
    task_id: str = Field(..., description=f"ID задачи")
    worker_id: str = Field(..., description=f"ID воркера")

    event: Event = Field(..., description=f"Данные события")
