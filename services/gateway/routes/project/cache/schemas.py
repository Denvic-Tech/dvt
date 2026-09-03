from typing import Optional, List

from pydantic import BaseModel, Field

from src.schemas.http.common import CommonResponse


class ClearProjectCacheBaseRequest(BaseModel):
    node_ids: Optional[List[str]] = Field(None, description="List of node IDs to invalidate cache for")


class ClearProjectCacheRequest(ClearProjectCacheBaseRequest):
    """Payload for clearing project's whole cache"""

    send_metadata_task: Optional[bool] = Field(
        True,
        description="Whether or not to send a metadata inferring task to the worker"
    )


class ClearProjectDataCacheRequest(ClearProjectCacheBaseRequest):
    """Payload for clearing project's data cache"""


class ClearProjectMetadataCacheRequest(ClearProjectCacheRequest):
    """Payload for clearing project's metadata cache"""


class ClearProjectCacheBaseResponse(CommonResponse):
    cleared_keys: List[str] = Field(default_factory=list, description="List of cleared keys to invalidate metadata cache for")


class ClearProjectCacheResponse(ClearProjectCacheBaseResponse):
    """Response for clearing project's whole cache"""

    task_id: Optional[str] = Field(None, description="ID of the task to invalidate metadata cache for")


class ClearProjectDataCacheResponse(ClearProjectCacheBaseResponse):
    """Response for clearing project's data cache"""


class ClearProjectMetadataCacheResponse(ClearProjectCacheResponse):
    """Response for clearing project's metadata cache"""
