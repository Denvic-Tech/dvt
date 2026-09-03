from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .exceptions import InvalidAccessScopeError
from .types import MCP_SCOPE_SCHEMA_VERSION, ResourceScopeMode


@dataclass(frozen=True, slots=True)
class ResourceScope:
    mode: ResourceScopeMode
    ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        normalized = frozenset(item.strip() for item in self.ids if item and item.strip())
        object.__setattr__(self, "ids", normalized)
        if self.mode is ResourceScopeMode.ALL and normalized:
            raise InvalidAccessScopeError(
                "Resource scope with mode=all must have an empty ids list."
            )

    def allows(self, resource_id: str) -> bool:
        return self.mode is ResourceScopeMode.ALL or resource_id in self.ids

    def to_mapping(self) -> dict[str, Any]:
        return {"mode": self.mode.value, "ids": sorted(self.ids)}

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, field_name: str) -> ResourceScope:
        try:
            mode = ResourceScopeMode(str(payload.get("mode", "")))
        except ValueError as exc:
            raise InvalidAccessScopeError(
                f"{field_name}.mode must be 'all' or 'selected'."
            ) from exc
        ids = payload.get("ids", [])
        if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
            raise InvalidAccessScopeError(f"{field_name}.ids must be a list of strings.")
        return cls(mode=mode, ids=frozenset(ids))


@dataclass(frozen=True, slots=True)
class MCPAccessScope:
    projects: ResourceScope
    db_connections: ResourceScope
    schema_version: int = MCP_SCOPE_SCHEMA_VERSION
    purpose: str = "mcp"

    def __post_init__(self) -> None:
        if self.schema_version != MCP_SCOPE_SCHEMA_VERSION:
            raise InvalidAccessScopeError(
                f"Unsupported MCP access scope schema version: {self.schema_version}."
            )
        if self.purpose != "mcp":
            raise InvalidAccessScopeError("MCP access scope purpose must be 'mcp'.")

    def allows_project(self, project_id: str) -> bool:
        return self.projects.allows(project_id)

    def allows_connection(self, connection_id: str) -> bool:
        return self.db_connections.allows(connection_id)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "purpose": self.purpose,
            "projects": self.projects.to_mapping(),
            "db_connections": self.db_connections.to_mapping(),
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> MCPAccessScope:
        if payload is None:
            raise InvalidAccessScopeError("MCP tokens require an access scope.")
        projects = payload.get("projects")
        db_connections = payload.get("db_connections")
        if not isinstance(projects, Mapping) or not isinstance(db_connections, Mapping):
            raise InvalidAccessScopeError(
                "MCP access scope requires projects and db_connections objects."
            )
        return cls(
            schema_version=int(payload.get("schema_version", 0)),
            purpose=str(payload.get("purpose", "")),
            projects=ResourceScope.from_mapping(projects, field_name="projects"),
            db_connections=ResourceScope.from_mapping(
                db_connections,
                field_name="db_connections",
            ),
        )
