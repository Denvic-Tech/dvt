from typing import Any, Optional

from pydantic import BaseModel, Field


class JSONData(BaseModel):
    data: Any = Field(..., description="JSON payload (dict/list/primitive)")
    total_items: Optional[int] = Field(
        None,
        description="Total items count if payload is a list, otherwise None",
    )

