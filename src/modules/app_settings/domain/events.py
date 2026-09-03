from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AppSettingEvent:
    key: str
    version: int
    changed_at: datetime


@dataclass(frozen=True)
class AppSettingCreated(AppSettingEvent):
    pass


@dataclass(frozen=True)
class AppSettingUpdated(AppSettingEvent):
    pass


@dataclass(frozen=True)
class AppSettingDeleted(AppSettingEvent):
    pass
