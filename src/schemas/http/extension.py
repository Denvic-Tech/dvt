from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.enums import ExtensionDepsStatus


class ExtensionManifestNodeSchema(BaseModel):
    name: str
    display_name: str
    description: str = ""


class ExtensionManifestBackendSchema(BaseModel):
    nodes_dir: str | None = None
    gateway_entrypoint: str | None = None
    migrations_dir: str | None = None


class ExtensionManifestFrontendSchema(BaseModel):
    dist_dir: str = "frontend/dist"
    entry_file: str = "index.js"
    entrypoint: str | None = None


class ExtensionManifestSchema(BaseModel):
    name: str = ""
    version: str = ""
    dvt_version: str | None = None
    display_name: str | None = None
    description: str = ""
    repository_url: str | None = None
    homepage_url: str | None = None
    backend: ExtensionManifestBackendSchema = Field(default_factory=ExtensionManifestBackendSchema)
    frontend: ExtensionManifestFrontendSchema | None = None
    requirements: list[str] = Field(default_factory=list)
    state_schema: dict[str, Any] = Field(default_factory=dict)
    nodes: list[ExtensionManifestNodeSchema] = Field(default_factory=list)


class ExtensionReadSchema(BaseModel):
    id: str | None = None
    name: str
    display_name: str
    description: str = ""
    repository_url: str | None = None
    is_enabled: bool
    is_installed: bool
    deps_status: ExtensionDepsStatus = ExtensionDepsStatus.NOT_INSTALLED
    current_version: str | None = None
    last_version: str | None = None
    install_path: str | None = None
    manifest_json: ExtensionManifestSchema = Field(default_factory=ExtensionManifestSchema)
    state_json: dict[str, Any] = Field(default_factory=dict)
    available_versions: list[str] = Field(default_factory=list)
    error_message: str | None = None
    installed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ExtensionStateReadSchema(BaseModel):
    extension_name: str
    state_key: str = "default"
    value: dict[str, Any] = Field(default_factory=dict)


class ExtensionStateUpdateSchema(BaseModel):
    value: dict[str, Any] = Field(default_factory=dict)


class ExtensionUninstallSchema(BaseModel):
    drop_extension_data: bool = False


class ExtensionCreateSchema(BaseModel):
    name: str
    display_name: str | None = None
    description: str | None = None
    repository_url: str | None = None


class ExtensionFrontendReadSchema(BaseModel):
    extension_name: str
    installed: bool
    bundle_url: str
    entry_file: str
    entrypoint: str | None = None
