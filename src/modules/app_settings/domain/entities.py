from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SettingValue:
    key: str
    value: Any
    version: int = 1
    updated_at: datetime | None = None
    updated_by: str | None = None


@dataclass(frozen=True)
class SettingChange:
    key: str
    old_value: Any
    new_value: Any
    changed_at: datetime
    changed_by: str | None = None
    change_reason: str | None = None
