from typing import Any, Optional

from pydantic import BaseModel, Field


class ExtensionNodeManifest(BaseModel):
    name: str
    display_name: str
    description: str = ""


class ExtensionBackendManifest(BaseModel):
    nodes_dir: str | None = None
    gateway_entrypoint: str | None = None
    migrations_dir: str | None = None


class ExtensionFrontendManifest(BaseModel):
    dist_dir: str = Field(default="frontend/dist")
    entry_file: str = Field(default="index.js")
    entrypoint: str | None = None


class ExtensionManifest(BaseModel):
    name: str
    version: str
    dvt_version: str | None = None
    display_name: str | None = None
    description: str = ""
    repository_url: str | None = None
    homepage_url: str | None = None
    backend: ExtensionBackendManifest = Field(default_factory=ExtensionBackendManifest)
    frontend: ExtensionFrontendManifest | None = None
    requirements: list[str] = Field(default_factory=list)
    state_schema: dict[str, Any] = Field(default_factory=dict)
    nodes: list[ExtensionNodeManifest] = Field(default_factory=list)
