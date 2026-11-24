from pydantic import BaseModel, ConfigDict

from src.modules.project.domain import ShuffleMethod


class ProjectSettings(BaseModel):
    """Project Settings"""

    model_config = ConfigDict(from_attributes=True)

    store_enabled: bool | None = False
    ttl_time: int | None = 0
    workers_count: int | None = 0
    shuffle_method: ShuffleMethod | None = None
