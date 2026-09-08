from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.node_dsl.base_node.base import BaseNode


class NodePackageManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]


@dataclass(frozen=True, slots=True)
class NodePackageDescriptor:
    node_name: str
    node_cls: type[BaseNode]
    package_module: str
    package_path: Path | None
    manifest: NodePackageManifest | None
    provider: Literal["builtin", "extension"]
    extension_name: str | None = None
    extension_version: str | None = None
    legacy: bool = False
