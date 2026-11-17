from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .types import (
    ConflictDecision,
    ConnectionDecisionAction,
    ImportMode,
    MergeStrategy,
    TransferWarningCode,
)


@dataclass(frozen=True)
class TransferActor:
    """Identity of the user performing an export or import."""

    user_id: str
    organization_id: str
    is_admin: bool = False
    has_global_access: bool = False

    @property
    def can_manage_schedules(self) -> bool:
        return self.is_admin or self.has_global_access


@dataclass(frozen=True)
class ExportSelection:
    project_ids: tuple[str, ...] = ()
    folder_ids: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.project_ids and not self.folder_ids


@dataclass(frozen=True)
class ExportOptions:
    include_variables: bool = False
    include_connections: bool = True
    include_secrets: bool = False
    include_files: bool = True
    include_schedule: bool = False
    disable_schedule_after_export: bool = False
    passphrase: str | None = None

    def public_dict(self) -> dict[str, bool]:
        """Options as recorded in the manifest, without the passphrase."""
        return {
            "include_variables": self.include_variables,
            "include_connections": self.include_connections,
            "include_secrets": self.include_secrets,
            "include_files": self.include_files,
            "include_schedule": self.include_schedule,
        }


@dataclass(frozen=True)
class ImportTarget:
    mode: ImportMode
    folder_id: str | None = None
    project_id: str | None = None
    merge_strategy: MergeStrategy = MergeStrategy.APPEND


@dataclass(frozen=True)
class ConnectionDecision:
    action: ConnectionDecisionAction
    connection_id: str | None = None
    secrets: dict[str, Any] | None = None


@dataclass(frozen=True)
class VariableDecision:
    """Per-key import decision: an overriding typed payload and/or conflict resolution."""

    value: dict[str, Any] | None = None
    conflict: ConflictDecision = ConflictDecision.KEEP


@dataclass(frozen=True)
class ScheduleDecision:
    import_schedule: bool = False
    enable: bool = False
    conflict: ConflictDecision = ConflictDecision.KEEP


@dataclass
class ImportDecisions:
    connections: dict[str, ConnectionDecision] = field(default_factory=dict)
    variables: dict[str, dict[str, VariableDecision]] = field(default_factory=dict)
    schedule: ScheduleDecision = field(default_factory=ScheduleDecision)
    passphrase: str | None = None


@dataclass(frozen=True)
class TransferWarning:
    code: TransferWarningCode
    message: str
    project_ref: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConnectionBinding:
    """A node input that must hold a connection identifier."""

    node_ui_id: str
    input_name: str
    connection_ref: str


@dataclass(frozen=True)
class NodeTypeInfo:
    """What this instance knows about a node class name."""

    name: str
    known: bool
    extension_name: str | None = None
    extension_version: str | None = None
    extension_available: bool = True
    connection_input_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExistingConnection:
    id: str
    name: str
    kind: str
    type: str


@dataclass(frozen=True)
class InstanceInfo:
    instance_id: str
    version: str
