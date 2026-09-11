from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExtensionNodeManifest:
    name: str
    display_name: str
    description: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ExtensionNodeManifest:
        return cls(
            name=str(payload.get("name") or ""),
            display_name=str(payload.get("display_name") or payload.get("name") or ""),
            description=str(payload.get("description") or ""),
        )

    def model_dump(self, *, mode: str | None = None, exclude_none: bool = False) -> dict[str, Any]:
        del mode, exclude_none
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
        }


@dataclass(frozen=True)
class ExtensionBackendManifest:
    nodes_dir: str | None = None
    gateway_entrypoint: str | None = None
    migrations_dir: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> ExtensionBackendManifest:
        data = payload or {}
        return cls(
            nodes_dir=data.get("nodes_dir"),
            gateway_entrypoint=data.get("gateway_entrypoint"),
            migrations_dir=data.get("migrations_dir"),
        )

    def model_dump(self, *, mode: str | None = None, exclude_none: bool = False) -> dict[str, Any]:
        del mode
        payload = {
            "nodes_dir": self.nodes_dir,
            "gateway_entrypoint": self.gateway_entrypoint,
            "migrations_dir": self.migrations_dir,
        }
        return _drop_none(payload) if exclude_none else payload


@dataclass(frozen=True)
class ExtensionFrontendManifest:
    dist_dir: str = "frontend/dist"
    entry_file: str = "index.js"
    entrypoint: str | None = None

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> ExtensionFrontendManifest:
        data = payload or {}
        return cls(
            dist_dir=str(data.get("dist_dir") or "frontend/dist"),
            entry_file=str(data.get("entry_file") or "index.js"),
            entrypoint=data.get("entrypoint"),
        )

    def model_dump(self, *, mode: str | None = None, exclude_none: bool = False) -> dict[str, Any]:
        del mode
        payload = {
            "dist_dir": self.dist_dir,
            "entry_file": self.entry_file,
            "entrypoint": self.entrypoint,
        }
        return _drop_none(payload) if exclude_none else payload


@dataclass(frozen=True)
class ExtensionManifest:
    name: str
    version: str
    dvt_version: str | None = None
    display_name: str | None = None
    description: str = ""
    repository_url: str | None = None
    homepage_url: str | None = None
    backend: ExtensionBackendManifest | Mapping[str, Any] = field(
        default_factory=ExtensionBackendManifest
    )
    frontend: ExtensionFrontendManifest | Mapping[str, Any] | None = None
    requirements: list[str] = field(default_factory=list)
    state_schema: Mapping[str, Any] = field(default_factory=dict)
    nodes: list[ExtensionNodeManifest | Mapping[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.backend, Mapping):
            object.__setattr__(
                self,
                "backend",
                ExtensionBackendManifest.from_mapping(self.backend),
            )
        if self.frontend is not None and isinstance(self.frontend, Mapping):
            object.__setattr__(
                self,
                "frontend",
                ExtensionFrontendManifest.from_mapping(self.frontend),
            )
        object.__setattr__(
            self,
            "requirements",
            [
                item
                for item in self.requirements
                if isinstance(item, str) and item.strip()
            ],
        )
        object.__setattr__(self, "state_schema", dict(self.state_schema or {}))
        object.__setattr__(
            self,
            "nodes",
            [
                item
                if isinstance(item, ExtensionNodeManifest)
                else ExtensionNodeManifest.from_mapping(item)
                for item in self.nodes
                if isinstance(item, (ExtensionNodeManifest, Mapping))
            ],
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ExtensionManifest:
        return cls(
            name=str(payload.get("name") or ""),
            version=str(payload.get("version") or ""),
            dvt_version=payload.get("dvt_version"),
            display_name=payload.get("display_name"),
            description=str(payload.get("description") or ""),
            repository_url=payload.get("repository_url"),
            homepage_url=payload.get("homepage_url"),
            backend=payload.get("backend") or {},
            frontend=payload.get("frontend"),
            requirements=list(payload.get("requirements") or []),
            state_schema=dict(payload.get("state_schema") or {}),
            nodes=list(payload.get("nodes") or []),
        )

    @classmethod
    def model_validate(cls, payload: Mapping[str, Any]) -> ExtensionManifest:
        """Compatibility helper for callers migrating from Pydantic manifests."""
        return cls.from_mapping(payload)

    def to_dict(self, *, exclude_none: bool = False) -> dict[str, Any]:
        backend = self.backend
        assert isinstance(backend, ExtensionBackendManifest)
        frontend = self.frontend
        assert frontend is None or isinstance(frontend, ExtensionFrontendManifest)
        payload: dict[str, Any] = {
            "name": self.name,
            "version": self.version,
            "dvt_version": self.dvt_version,
            "display_name": self.display_name,
            "description": self.description,
            "repository_url": self.repository_url,
            "homepage_url": self.homepage_url,
            "backend": backend.model_dump(exclude_none=exclude_none),
            "frontend": (
                frontend.model_dump(exclude_none=exclude_none)
                if frontend is not None
                else None
            ),
            "requirements": list(self.requirements),
            "state_schema": dict(self.state_schema),
            "nodes": [item.model_dump(exclude_none=exclude_none) for item in self.nodes],
        }
        return _drop_none(payload) if exclude_none else payload

    def model_dump(
        self,
        *,
        mode: str | None = None,
        exclude_none: bool = False,
    ) -> dict[str, Any]:
        """Compatibility helper for callers migrating from Pydantic manifests."""
        del mode
        return self.to_dict(exclude_none=exclude_none)


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _drop_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


@dataclass(frozen=True)
class ExtensionFrontendBundle:
    bundle_path: Path
    assets_root: Path
    entry_file: str
    entrypoint: str | None


@dataclass(frozen=True)
class ExtensionPackagePreview:
    package_id: str
    filename: str
    name: str
    display_name: str
    version: str
    current_version: str | None
    dvt_version: str | None
    operation: str
    compatible: bool
    offline_ready: bool
    has_wheelhouse: bool
    bundled_wheels_count: int
    warnings: tuple[str, ...] = ()


__all__ = [
    "ExtensionBackendManifest",
    "ExtensionFrontendBundle",
    "ExtensionFrontendManifest",
    "ExtensionManifest",
    "ExtensionNodeManifest",
    "ExtensionPackagePreview",
]
