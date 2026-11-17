"""Transport schemas: bundle documents stored inside the archive and HTTP payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.modules.project_transfer.domain.types import (
    ConflictDecision,
    ConnectionDecisionAction,
    ImportMode,
    MergeStrategy,
    TransferWarningCode,
)
from src.schemas.http.project_variable import ProjectVariableBase

# --- Bundle documents --------------------------------------------------------


class BundleFolderDoc(BaseModel):
    ref: str
    name: str
    parent_ref: str | None = None


class ManifestProjectEntryDoc(BaseModel):
    ref: str
    name: str
    folder_ref: str | None = None


class RequiredNodeTypeDoc(BaseModel):
    name: str
    extension_name: str | None = None
    extension_version: str | None = None


class BundleManifestDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")

    format_version: int
    dvt_version: str
    exported_at: datetime
    source_instance_id: str
    options: dict[str, bool] = Field(default_factory=dict)
    required_node_types: list[RequiredNodeTypeDoc] = Field(default_factory=list)
    has_secrets: bool = False
    folders: list[BundleFolderDoc] = Field(default_factory=list)
    projects: list[ManifestProjectEntryDoc] = Field(default_factory=list)


class GraphSubgraphDoc(BaseModel):
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


class GraphNodeDoc(BaseModel):
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
    input_values: dict[str, Any] | None = Field(default_factory=dict)
    subgraph_id: str | None = None


class GraphEdgeDoc(BaseModel):
    ui_id: str
    type: str
    source: str
    target: str
    source_handle: str | None = None
    target_handle: str | None = None
    subgraph_id: str | None = None


class ColumnAnnotationDoc(BaseModel):
    node_ui_id: str
    port: str
    column: str
    description: str
    origin_key: str | None = None


class GraphDoc(BaseModel):
    subgraphs: list[GraphSubgraphDoc] = Field(default_factory=list)
    nodes: list[GraphNodeDoc] = Field(default_factory=list)
    edges: list[GraphEdgeDoc] = Field(default_factory=list)
    # Optional since bundles written before node column descriptions existed omit it.
    column_annotations: list[ColumnAnnotationDoc] = Field(default_factory=list)


class ProjectMetaDoc(BaseModel):
    name: str
    store_enabled: bool | None = False
    ttl_time: int | None = 0
    workers_count: int | None = 0


class ProjectFileDoc(BaseModel):
    storage_path: str
    is_dir: bool = False
    size: int = 0
    sha256: str | None = None
    content_type: str | None = None


class ScheduleDoc(BaseModel):
    cron: str
    mode: str
    force_exec: bool = False
    max_retries: int = 0
    retry_delay_seconds: int = 60
    retry_backoff: str = "fixed"
    retry_max_delay_seconds: int = 3600
    disabled: bool = False


class ConnectionBindingDoc(BaseModel):
    node_ui_id: str
    input_name: str
    connection_ref: str


class BundleProjectDoc(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ref: str
    folder_ref: str | None = None
    meta: ProjectMetaDoc
    variables: dict[str, dict[str, Any]] | None = None
    graph: GraphDoc = Field(default_factory=GraphDoc)
    files: list[ProjectFileDoc] = Field(default_factory=list)
    schedule: ScheduleDoc | None = None
    connection_bindings: list[ConnectionBindingDoc] = Field(default_factory=list)


class BundleConnectionDoc(BaseModel):
    ref: str
    name: str
    kind: str
    type: str
    driver: str | None = None
    driver_options: dict[str, Any] | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)
    inaccessible: bool = False


class ConnectionsDoc(BaseModel):
    connections: list[BundleConnectionDoc] = Field(default_factory=list)


# --- HTTP -------------------------------------------------------------------


class ExportRequestSchema(BaseModel):
    project_ids: list[str] = Field(default_factory=list, description="ID проектов для экспорта")
    folder_ids: list[str] = Field(
        default_factory=list,
        description="ID папок для экспорта вместе со всеми вложенными папками и проектами",
    )
    include_variables: bool = Field(False, description="Экспортировать переменные проекта со значениями")
    include_connections: bool = Field(True, description="Экспортировать описания подключений без секретов")
    include_secrets: bool = Field(
        False,
        description="Экспортировать секреты подключений, защищённые паролем",
    )
    passphrase: str | None = Field(None, description="Пароль для защиты секретов (обязателен при include_secrets)")
    include_files: bool = Field(True, description="Экспортировать файлы, загруженные в ноды")
    include_schedule: bool = Field(False, description="Экспортировать настройки расписания")
    disable_schedule_after_export: bool = Field(
        False,
        description="Выключить расписание экспортированных проектов после экспорта (только администраторы)",
    )


class ConnectionDecisionSchema(BaseModel):
    action: ConnectionDecisionAction = Field(..., description="Что сделать с подключением из бандла")
    connection_id: str | None = Field(None, description="ID существующего подключения для use_existing")
    secrets: dict[str, Any] | None = Field(
        None,
        description="Секреты для create, если они не берутся из бандла",
    )


class VariableDecisionSchema(BaseModel):
    value: ProjectVariableBase | None = Field(None, description="Значение, заменяющее значение из бандла")
    conflict: ConflictDecision = Field(
        ConflictDecision.KEEP,
        description="Что делать при совпадении ключа с существующей переменной (merge)",
    )


class ScheduleDecisionSchema(BaseModel):
    import_schedule: bool = Field(False, description="Импортировать расписание из бандла")
    enable: bool = Field(False, description="Включить расписание после импорта")
    conflict: ConflictDecision = Field(
        ConflictDecision.KEEP,
        description="Что делать, если у целевого проекта уже есть расписание (merge)",
    )


class ImportRequestSchema(BaseModel):
    mode: ImportMode = Field(ImportMode.CREATE, description="create: новые проекты, merge: в существующий проект")
    folder_id: str | None = Field(None, description="Целевая папка для create, null означает корень")
    project_id: str | None = Field(None, description="Целевой проект для merge")
    merge_strategy: MergeStrategy = Field(
        MergeStrategy.APPEND,
        description="replace: удалить текущий граф перед импортом, append: добавить рядом",
    )
    passphrase: str | None = Field(None, description="Пароль от секретов бандла")
    connections: dict[str, ConnectionDecisionSchema] = Field(
        default_factory=dict,
        description="Решения по подключениям бандла по их ref",
    )
    variables: dict[str, dict[str, VariableDecisionSchema]] = Field(
        default_factory=dict,
        description="Решения по переменным: project_ref -> ключ -> решение",
    )
    schedule: ScheduleDecisionSchema = Field(default_factory=ScheduleDecisionSchema)


class TransferWarningSchema(BaseModel):
    code: TransferWarningCode
    message: str
    project_ref: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ManifestInfoSchema(BaseModel):
    format_version: int
    dvt_version: str
    exported_at: datetime
    source_instance_id: str
    options: dict[str, bool]
    has_secrets: bool


class ExistingConnectionSchema(BaseModel):
    id: str
    name: str
    kind: str
    type: str


class ConnectionPreviewSchema(BaseModel):
    ref: str
    name: str
    kind: str
    type: str
    inaccessible: bool
    has_secrets_in_bundle: bool
    candidates: list[ExistingConnectionSchema] = Field(default_factory=list)


class VariablePreviewSchema(BaseModel):
    key: str
    value: ProjectVariableBase | None = None
    conflicts_with_existing: bool = False


class ProjectPreviewSchema(BaseModel):
    ref: str
    name: str
    folder_ref: str | None
    node_count: int
    edge_count: int
    subgraph_count: int
    files_total_size: int
    variables: list[VariablePreviewSchema]
    has_schedule_in_bundle: bool
    has_existing_schedule: bool


class ImportPreviewSchema(BaseModel):
    manifest: ManifestInfoSchema
    folders: list[BundleFolderDoc]
    projects: list[ProjectPreviewSchema]
    connections: list[ConnectionPreviewSchema]
    unknown_node_names: list[str]
    unavailable_extensions: list[str]
    target_has_graph: bool
    can_manage_schedules: bool
    warnings: list[TransferWarningSchema]


class ImportResultSchema(BaseModel):
    folder_ids: dict[str, str] = Field(default_factory=dict, description="ref папки -> ID созданной папки")
    project_ids: dict[str, str] = Field(default_factory=dict, description="ref проекта -> ID проекта")
    connection_ids: dict[str, str] = Field(default_factory=dict, description="ref подключения -> ID подключения")
    skipped_connection_refs: list[str] = Field(default_factory=list)
    warnings: list[TransferWarningSchema] = Field(default_factory=list)
