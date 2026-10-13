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
