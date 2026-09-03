from pydantic import BaseModel, ConfigDict


class ProjectSettings(BaseModel):
    """Project Settings"""

    model_config = ConfigDict(from_attributes=True)

    store_enabled: bool | None = False
    ttl_time: int | None = 0
    workers_count: int | None = 0
