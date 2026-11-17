from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .value_objects import ConnectionBinding, TransferWarning


@dataclass
class GraphSubgraphSnapshot:
    """Transferable subgraph state without persistence identifiers."""

    ui_id: str
    type: str
    position_x: float
    position_y: float
    name: str
    display_name: str
    selected: bool = False
    expanded: bool = True
    comment: str | None = None
    color: str | None = None


@dataclass
class GraphNodeSnapshot:
    """Transferable node state without persistence identifiers."""

    ui_id: str
    type: str
    position_x: float
    position_y: float
    name: str
    display_name: str
    selected: bool = False
    comment: str | None = None
    show_signal_io: bool = False
    show_variables_io: bool = False
    store_enabled: bool | None = False
    input_values: dict[str, Any] | None = field(default_factory=dict)
    subgraph_id: str | None = None


@dataclass
class GraphEdgeSnapshot:
    """Transferable edge state without persistence identifiers."""

    ui_id: str
    type: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None
    subgraph_id: str | None = None


@dataclass
class ColumnAnnotationSnapshot:
    """Description of one node port column; travels with the graph it annotates."""

    node_ui_id: str
    port: str
    column: str
    description: str
    origin_key: str | None = None


@dataclass
class GraphSnapshot:
    """Full computational and visual graph of one project."""

    subgraphs: list[GraphSubgraphSnapshot] = field(default_factory=list)
    nodes: list[GraphNodeSnapshot] = field(default_factory=list)
    edges: list[GraphEdgeSnapshot] = field(default_factory=list)
    column_annotations: list[ColumnAnnotationSnapshot] = field(default_factory=list)


@dataclass
class GraphIdMapping:
    """Old ui_id -> new ui_id for every graph element produced by a remap."""

    subgraphs: dict[str, str] = field(default_factory=dict)
    nodes: dict[str, str] = field(default_factory=dict)
    edges: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ServiceFilesPrefixRewrite:
    """Storage prefix move of node-attached files produced by a graph remap."""

    old_root_prefix: str
    new_root_prefix: str


@dataclass
class GraphRemapResult:
    snapshot: GraphSnapshot
    mapping: GraphIdMapping
    service_files_rewrites: list[ServiceFilesPrefixRewrite] = field(default_factory=list)


# --- Bundle -----------------------------------------------------------------


@dataclass
class ProjectMeta:
    name: str
    store_enabled: bool | None = False
    ttl_time: int | None = 0
    workers_count: int | None = 0


@dataclass
class ProjectFile:
    """One node-attached file object of a project, addressed by its storage path."""

    storage_path: str
    is_dir: bool = False
    size: int = 0
    sha256: str | None = None
    content_type: str | None = None
    content: bytes | None = None

    @property
    def parent_path(self) -> str:
        return self.storage_path.rsplit("/", 1)[0] if "/" in self.storage_path else ""

    @property
    def name(self) -> str:
        return self.storage_path.rsplit("/", 1)[-1]


@dataclass
class ScheduleSnapshot:
    cron: str
    mode: str
    force_exec: bool = False
    max_retries: int = 0
    retry_delay_seconds: int = 60
    retry_backoff: str = "fixed"
    retry_max_delay_seconds: int = 3600
    disabled: bool = False


@dataclass
class BundleFolder:
    ref: str
    name: str
    parent_ref: str | None = None


@dataclass
class BundleConnection:
    """Connection without secrets; enough to recreate it once secrets are supplied."""

    ref: str
    name: str
    kind: str
    type: str
    driver: str | None = None
    driver_options: dict[str, Any] | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    inaccessible: bool = False


@dataclass
class BundleProject:
    ref: str
    meta: ProjectMeta
    folder_ref: str | None = None
    graph: GraphSnapshot = field(default_factory=GraphSnapshot)
    variables: dict[str, dict[str, Any]] | None = None
    files: list[ProjectFile] = field(default_factory=list)
    schedule: ScheduleSnapshot | None = None
    connection_bindings: list[ConnectionBinding] = field(default_factory=list)

    @property
    def connection_refs(self) -> set[str]:
        return {binding.connection_ref for binding in self.connection_bindings}


@dataclass
class RequiredNodeType:
    """A node class the bundle depends on; ``name`` is the registry key."""

    name: str
    extension_name: str | None = None
    extension_version: str | None = None


@dataclass
class BundleManifest:
    format_version: int
    dvt_version: str
    exported_at: datetime
    source_instance_id: str
    options: dict[str, bool] = field(default_factory=dict)
    required_node_types: list[RequiredNodeType] = field(default_factory=list)
    has_secrets: bool = False


@dataclass
class ProjectBundle:
    manifest: BundleManifest
    folders: list[BundleFolder] = field(default_factory=list)
    projects: list[BundleProject] = field(default_factory=list)
    connections: list[BundleConnection] = field(default_factory=list)
    secrets: dict[str, dict[str, Any]] | None = None
    """Connection secrets by connection ref; only present in memory, never serialized as-is."""
    encrypted_secrets: bytes | None = None
    """Passphrase-protected serialized form of ``secrets``."""

    def connection_by_ref(self, ref: str) -> BundleConnection | None:
        return next((connection for connection in self.connections if connection.ref == ref), None)

    def project_by_ref(self, ref: str) -> BundleProject | None:
        return next((project for project in self.projects if project.ref == ref), None)


# --- Source-side (export) ---------------------------------------------------


@dataclass
class SourceFolder:
    id: str
    name: str
    parent_id: str | None
    organization_id: str


@dataclass
class SourceProject:
    id: str
    folder_id: str | None
    organization_id: str
    meta: ProjectMeta
    variables: dict[str, dict[str, Any]] | None = None


@dataclass
class ExportResult:
    bundle: ProjectBundle
    warnings: list[TransferWarning] = field(default_factory=list)
    file_name: str = "dvt-export"
    schedule_project_ids: list[str] = field(default_factory=list)
    """Exported projects whose schedule is active and may be disabled after export."""


# --- Target-side (import) ---------------------------------------------------


@dataclass
class TargetFolder:
    id: str
    organization_id: str
    depth: int


@dataclass
class TargetProject:
    id: str
    name: str
    organization_id: str
    user_id: str
    variables: dict[str, dict[str, Any]] | None
    has_graph: bool
    has_schedule: bool


@dataclass
class ConnectionPreview:
    ref: str
    name: str
    kind: str
    type: str
    inaccessible: bool
    has_secrets_in_bundle: bool
    candidates: list[Any] = field(default_factory=list)
    """Existing connections of the same type and name on this instance."""


@dataclass
class VariablePreview:
    key: str
    value: dict[str, Any] | None
    conflicts_with_existing: bool = False


@dataclass
class ProjectPreview:
    ref: str
    name: str
    folder_ref: str | None
    node_count: int
    edge_count: int
    subgraph_count: int
    files_total_size: int
    variables: list[VariablePreview]
    has_schedule_in_bundle: bool
    has_existing_schedule: bool = False


@dataclass
class ImportPreview:
    manifest: BundleManifest
    folders: list[BundleFolder]
    projects: list[ProjectPreview]
    connections: list[ConnectionPreview]
    unknown_node_names: list[str]
    unavailable_extensions: list[str]
    target_has_graph: bool = False
    can_manage_schedules: bool = False
    warnings: list[TransferWarning] = field(default_factory=list)


@dataclass
class ImportResult:
    folder_ids: dict[str, str] = field(default_factory=dict)
    """Bundle folder ref -> created folder id."""
    project_ids: dict[str, str] = field(default_factory=dict)
    """Bundle project ref -> created or merged project id."""
    connection_ids: dict[str, str] = field(default_factory=dict)
    """Bundle connection ref -> resolved connection id (existing or created)."""
    skipped_connection_refs: list[str] = field(default_factory=list)
    warnings: list[TransferWarning] = field(default_factory=list)
