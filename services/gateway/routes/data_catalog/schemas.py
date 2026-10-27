from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FreshnessLiteral = Literal["fresh", "stale", "unverified", "unreachable", "not_found"]
CheckErrorKindLiteral = Literal["not_found", "unreachable"]
DirectionLiteral = Literal["read", "write"]
FieldProvenanceLiteral = Literal["declared", "source", "none"]
DatasetProvenanceLiteral = Literal["declared", "none"]


class DatasetLocatorSchema(BaseModel):
    """Адрес источника: вид и части адреса, которые понимает адаптер этого вида."""

    kind: str = Field(description="Source kind, e.g. `db_table`.")
    location: str = Field(description="Human-readable location in the source's own notation.")
    parts: dict[str, str | int | None] = Field(
        default_factory=dict,
        description="Kind-specific address parts; for `db_table`: dialect, host, port, database, schema, table.",
    )


class DatasetSummarySchema(BaseModel):
    id: str
    organization_id: str
    physical_key: str
    locator: DatasetLocatorSchema
    description: str | None = None
    effective_description: str | None = None
    description_provenance: DatasetProvenanceLiteral = "none"
    description_updated_by: str | None = None
    description_updated_at: datetime | None = None
    freshness: FreshnessLiteral
    schema_synced_at: datetime | None = None
    last_check_failed_at: datetime | None = None
    last_check_error: str | None = None
    last_check_error_kind: CheckErrorKindLiteral | None = None
    observed_at_run: datetime | None = None
    field_count: int = Field(ge=0)
    reader_count: int = Field(ge=0)
    writer_count: int = Field(ge=0)
    updated_at: datetime


class DatasetPageSchema(BaseModel):
    items: list[DatasetSummarySchema]
    next_cursor: str | None = None


class DatasetFieldSchema(BaseModel):
    id: str
    name: str
    dtype: str | None = None
    nullable: bool | None = None
    ordinal: int | None = None
    primary_key: bool = False
    source_comment: str | None = None
    description: str | None = None
    effective_description: str | None = None
    description_provenance: FieldProvenanceLiteral = "none"
    description_updated_by: str | None = None
    description_updated_at: datetime | None = None
    status: Literal["ok", "new", "missing", "type_changed"]
    first_seen_at: datetime
    last_seen_at: datetime
    observed_via: list[str] = Field(default_factory=list)


class DatasetDetailsSchema(BaseModel):
    id: str
    organization_id: str
    physical_key: str
    locator: DatasetLocatorSchema
    description: str | None = None
    effective_description: str | None = None
    description_provenance: DatasetProvenanceLiteral = "none"
    description_updated_by: str | None = None
    description_updated_at: datetime | None = None
    freshness: FreshnessLiteral
    schema_synced_at: datetime | None = None
    last_check_failed_at: datetime | None = None
    last_check_error: str | None = None
    last_check_error_kind: CheckErrorKindLiteral | None = None
    observed_at_run: datetime | None = None
    connection_ids: list[str] = Field(default_factory=list)
    fields: list[DatasetFieldSchema] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class DatasetUsageEntrySchema(BaseModel):
    project_id: str
    project_name: str | None = None
    node_id: str
    node_name: str
    direction: DirectionLiteral
    kind: Literal["declared"]
    resolved_via: Literal["const", "expression", "sql"]
    graph_revision: int
    updated_at: datetime


class DatasetUsageResponseSchema(BaseModel):
    items: list[DatasetUsageEntrySchema]


class FieldRefSchema(BaseModel):
    """Ссылка на поле: ровно одно из field_id или name."""

    model_config = ConfigDict(extra="forbid")

    field_id: str | None = Field(default=None, min_length=1)
    name: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _exactly_one(self) -> "FieldRefSchema":
        if (self.field_id is None) == (self.name is None):
            raise ValueError("Exactly one of field_id or name must be provided.")
        return self


class FieldDescriptionPatchSchema(FieldRefSchema):
    """Ключ description обязателен: null означает очистку, пропуск недопустим."""

    description: str | None = Field(max_length=20480)


class DatasetDescriptionPatchSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=20480)
    fields: list[FieldDescriptionPatchSchema] | None = None


class FieldRenameConfirmSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    missing: FieldRefSchema
    new: FieldRefSchema


class RefreshOutcomeSchema(BaseModel):
    status: Literal["synced", "failed", "no_connection", "unsupported"]
    new: int = Field(default=0, ge=0)
    missing: int = Field(default=0, ge=0)
    type_changed: int = Field(default=0, ge=0)
    affected_project_ids: list[str] = Field(default_factory=list)
    error: str | None = None
    error_kind: CheckErrorKindLiteral | None = None


LineageOpLiteral = Literal["source", "pass", "rename", "compute", "aggregate", "merge", "unknown"]
PortStatusLiteral = Literal["resolved", "partially_resolved", "unresolved"]
LineageProvenanceLiteral = Literal["declared", "source", "inherited", "derived", "none", "unknown"]
ExplainDirectionLiteral = Literal["upstream", "downstream"]


class LineageRefSchema(BaseModel):
    key: str = Field(description="`ds:<dataset_id>:<field_id>` или `node:<node_id>:<port>:<column>`.")
    kind: Literal["ds", "node"]
    dataset_id: str | None = None
    field_id: str | None = None
    node_id: str | None = None
    port: str | None = None
    column: str | None = None


class NodeFieldSchema(BaseModel):
    name: str
    ref: LineageRefSchema
    op: LineageOpLiteral
    origin: LineageRefSchema
    deps: list[LineageRefSchema] = Field(default_factory=list)
    deps_unknown: bool = False
    description: str | None = None
    description_provenance: LineageProvenanceLiteral = "unknown"
    description_source: LineageRefSchema | None = None
    description_updated_by: str | None = None
    description_updated_at: datetime | None = None
    explanation: str | None = None
    origin_field_name: str | None = Field(
        default=None, description="Имя поля сущности, если колонка происходит из него."
    )
    origin_location: str | None = Field(
        default=None, description="Человекочитаемый адрес сущности-источника колонки."
    )


class OrphanedAnnotationSchema(BaseModel):
    """Описание колонки, которой больше нет на порту: осталось после переименования в ноде."""

    column: str
    description: str
    origin_key: str | None = None
    description_updated_by: str | None = None
    updated_at: datetime


class NodeFieldsResponseSchema(BaseModel):
    project_id: str
    node_id: str
    node_name: str
    port: str
    role: Literal["output", "input"]
    status: PortStatusLiteral
    reason: str | None = None
    detail: str | None = None
    available_ports: list[str] = Field(default_factory=list)
    fields: list[NodeFieldSchema] = Field(default_factory=list)
    orphaned_annotations: list[OrphanedAnnotationSchema] = Field(default_factory=list)


class ColumnOccurrenceSchema(BaseModel):
    """Колонка одного порта внутри группы; `is_override` отмечает переопределение не на origin."""

    ref: LineageRefSchema
    node_id: str
    node_name: str
    port: str
    role: Literal["output", "input"]
    column: str
    op: LineageOpLiteral
    deps: list[LineageRefSchema] = Field(default_factory=list)
    deps_unknown: bool = False
    depth: int = Field(ge=0, description="Хопов от origin по pass/rename/source.")
    description: str | None = None
    description_provenance: LineageProvenanceLiteral = "unknown"
    description_source: LineageRefSchema | None = None
    description_updated_by: str | None = None
    description_updated_at: datetime | None = None
    is_override: bool = False


class ColumnGroupSchema(BaseModel):
    """Все вхождения колонки с общим origin; группа это представление, а не сущность хранения."""

    origin: LineageRefSchema
    kind: Literal["dataset_field", "node_column"]
    dataset_id: str | None = None
    dataset_location: str | None = None
    field_name: str | None = None
    origin_node_name: str | None = None
    description: str | None = None
    description_provenance: LineageProvenanceLiteral = "unknown"
    description_source: LineageRefSchema | None = None
    description_updated_by: str | None = None
    description_updated_at: datetime | None = None
    override_count: int = Field(default=0, ge=0)
    occurrences: list[ColumnOccurrenceSchema] = Field(default_factory=list)


class UnresolvedPortSchema(BaseModel):
    node_id: str
    node_name: str
    port: str
    role: Literal["output", "input"]
    status: PortStatusLiteral
    reason: str | None = None
    detail: str | None = None


class ProjectOrphanedAnnotationSchema(OrphanedAnnotationSchema):
    node_id: str
    port: str


class DescriptionTargetSchema(BaseModel):
    """Куда пишется описание строки: `project` через PATCH колонок ноды, `global` через PATCH сущности."""

    scope: Literal["project", "global"]
    node_id: str | None = None
    port: str | None = None
    column: str | None = None
    dataset_id: str | None = None
    field_id: str | None = None
    field_name: str | None = None


class ColumnRowSchema(BaseModel):
    """Отрезок цепочки с одним именем и одним текстом описания: строка общего окна каталога."""

    id: str = Field(description="Ключ стартового вхождения; стабилен, пока не меняется граф.")
    name: str
    origin: LineageRefSchema
    start: LineageRefSchema
    kind: Literal["dataset_field", "node_column"]
    dataset_id: str | None = None
    dataset_location: str | None = None
    field_name: str | None = None
    origin_node_name: str | None = None
    description: str | None = None
    description_provenance: LineageProvenanceLiteral = "unknown"
    description_source: LineageRefSchema | None = None
    description_updated_by: str | None = None
    description_updated_at: datetime | None = None
    is_rename: bool = False
    renamed_from: str | None = None
    is_refinement: bool = Field(
        default=False, description="Строка возникла из-за точечного описания в ноде старта."
    )
    targets: list[DescriptionTargetSchema] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list, description="id строк, из которых собрана колонка.")
    node_count: int = Field(default=0, ge=0)
    occurrences: list[ColumnOccurrenceSchema] = Field(default_factory=list)


class ProjectColumnsResponseSchema(BaseModel):
    project_id: str
    lineage_available: bool = Field(
        description="false, если у проекта нет документа lineage даже после ленивого repair."
    )
    truncated: bool = False
    rows: list[ColumnRowSchema] = Field(default_factory=list)
    groups: list[ColumnGroupSchema] = Field(default_factory=list)
    unresolved_ports: list[UnresolvedPortSchema] = Field(default_factory=list)
    orphaned_annotations: list[ProjectOrphanedAnnotationSchema] = Field(default_factory=list)


class ColumnDescriptionPatchSchema(BaseModel):
    """Ключ description обязателен: null удаляет описание колонки."""

    model_config = ConfigDict(extra="forbid")

    column: str = Field(min_length=1, max_length=512)
    description: str | None = Field(max_length=20480)


class NodeColumnDescriptionsPatchSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    port: str | None = Field(default=None, max_length=128)
    fields: list[ColumnDescriptionPatchSchema] = Field(min_length=1, max_length=2000)


class ExplainStepSchema(BaseModel):
    ref: LineageRefSchema
    depth: int = Field(ge=0)
    op: LineageOpLiteral
    text: str | None = None
    node_id: str | None = None
    node_name: str | None = None
    port: str | None = None
    column: str | None = None
    deps_unknown: bool = False
    dataset_id: str | None = None
    field_id: str | None = None
    field_name: str | None = None
    deps: list[LineageRefSchema] = Field(
        default_factory=list,
        description="Direct parents of this step; lets a client rebuild the tree without guessing by depth.",
    )


class LineageGapSchema(BaseModel):
    ref: LineageRefSchema
    reason: str
    detail: str | None = None


class FieldExplanationSchema(BaseModel):
    root: LineageRefSchema
    direction: ExplainDirectionLiteral
    description: str | None = None
    description_provenance: LineageProvenanceLiteral = "unknown"
    description_source: LineageRefSchema | None = None
    truncated: bool = False
    steps: list[ExplainStepSchema] = Field(default_factory=list)
    gaps: list[LineageGapSchema] = Field(default_factory=list)


class FieldDependentSchema(BaseModel):
    project_id: str
    node_id: str
    node_name: str
    port: str
    column: str
    op: LineageOpLiteral
    depth: int = Field(ge=1)
    ref: LineageRefSchema


class FieldDependentsResponseSchema(BaseModel):
    dataset_id: str
    field_id: str
    items: list[FieldDependentSchema] = Field(default_factory=list)
