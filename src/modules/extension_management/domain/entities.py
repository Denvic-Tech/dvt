from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.modules.extension_management.domain.types import ExtensionDependencyStatus


@dataclass
class Extension:
    name: str
    display_name: str
    description: str = ""
    id: str | None = None
    repository_url: str | None = None
    is_enabled: bool = True
    is_installed: bool = False
    deps_status: ExtensionDependencyStatus = ExtensionDependencyStatus.NOT_INSTALLED
    current_version: str | None = None
    last_version: str | None = None
    install_path: str | None = None
    manifest_json: dict[str, Any] = field(default_factory=dict)
    state_json: dict[str, Any] = field(default_factory=dict)
    available_versions: list[str] = field(default_factory=list)
    error_message: str | None = None
    installed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ExtensionCreate:
    name: str
    display_name: str | None = None
    description: str | None = None
    repository_url: str | None = None


__all__ = ["Extension", "ExtensionCreate"]
