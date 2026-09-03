from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AppSettingDefinitionSchema(BaseModel):
    key: str
    namespace: str
    group: str | None = None
    name: str
    value_type: dict[str, Any]
    nullable: bool
    default: Any = None
    ge: int | float | None = None
    le: int | float | None = None
    min_length: int | None = None
    max_length: int | None = None
    description: str | None = None
    secret: bool
    runtime_editable: bool
    bootstrap: bool
    required: bool
    read_env: bool
    env_var: str | None = None
    setup_label: str | None = None
    setup_type: str


class AppSettingHistoryItemSchema(BaseModel):
    key: str
    old_value: Any = None
    new_value: Any = None
    changed_at: datetime
    changed_by: str | None = None
    change_reason: str | None = None
