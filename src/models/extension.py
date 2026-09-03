from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON
from sqlmodel import Field, SQLModel

from src.enums import ExtensionDepsStatus

from .mixins import TimestampedModel


class ExtensionRecord(TimestampedModel, SQLModel, table=True):
    __tablename__ = "extensions"

    id: str | None = Field(default_factory=lambda: str(uuid4()), primary_key=True)

    name: str = Field(nullable=False, index=True, unique=True)
    display_name: str = Field(nullable=False)
    description: str = Field(default="", nullable=False)
    repository_url: str | None = Field(default=None, nullable=True)

    is_enabled: bool = Field(default=True, nullable=False)
    is_installed: bool = Field(default=False, nullable=False)
    deps_status: ExtensionDepsStatus = Field(default=ExtensionDepsStatus.NOT_INSTALLED, nullable=False)

    current_version: str | None = Field(default=None, nullable=True)
    last_version: str | None = Field(default=None, nullable=True)

    install_path: str | None = Field(default=None, nullable=True)

    manifest_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON, nullable=False)
    state_json: dict[str, Any] = Field(default_factory=dict, sa_type=JSON, nullable=False)
    available_versions: list[str] | None = Field(default_factory=list, sa_type=JSON, nullable=True)

    error_message: str | None = Field(default=None, nullable=True)
    installed_at: datetime | None = Field(default=None, nullable=True)
