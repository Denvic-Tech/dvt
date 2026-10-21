from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .catalog_values import DatasetLocator, ProjectionDiagnostic, ProjectionStamp
from .types import (
    CheckErrorKind,
    FieldStatus,
    Freshness,
    LinkDirection,
    LinkKind,
    ProjectionStatus,
    ResolvedVia,
)


@dataclass(slots=True)
class Dataset:
    id: str
    organization_id: str
    locator: DatasetLocator
    physical_key: str
    created_at: datetime
    updated_at: datetime
    location: str = ""
    description: str | None = None
    schema_synced_at: datetime | None = None
    last_check_failed_at: datetime | None = None
    description_updated_by: str | None = None
    description_updated_at: datetime | None = None
    observed_at_run: datetime | None = None
    last_check_error: str | None = None
    last_check_error_kind: CheckErrorKind | None = None

    @property
    def kind(self) -> str:
        return self.locator.kind


@dataclass(slots=True)
class DatasetField:
    id: str
    dataset_id: str
    name: str
    status: FieldStatus
    first_seen_at: datetime
    last_seen_at: datetime
    dtype: str | None = None
    nullable: bool | None = None
    ordinal: int | None = None
    primary_key: bool = False
    source_comment: str | None = None
    description: str | None = None
    observed_via: tuple[str, ...] = ()
    description_updated_by: str | None = None
    description_updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class DatasetConnection:
    dataset_id: str
    connection_id: str
    connection_revision: str
    first_seen_at: datetime
    last_seen_at: datetime


@dataclass(frozen=True, slots=True)
class DatasetLink:
    id: str
    dataset_id: str
    project_id: str
    organization_id: str
    node_id: str
    node_name: str
    direction: LinkDirection
    resolved_via: ResolvedVia
    graph_revision: int
    created_at: datetime
    updated_at: datetime
    kind: LinkKind = LinkKind.DECLARED


@dataclass(slots=True)
class ProjectCatalogProjection:
    project_id: str
    organization_id: str
    stamp: ProjectionStamp
    built_at: datetime
    status: ProjectionStatus
    depends_on_project_variables: bool = False
    error: str | None = None
    diagnostics: tuple[ProjectionDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class DatasetUsageEntry:
    project_id: str
    project_name: str | None
    node_id: str
    node_name: str
    direction: LinkDirection
    kind: LinkKind
    resolved_via: ResolvedVia
    graph_revision: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class DatasetSearchQuery:
    text: str | None = None
    connection_id: str | None = None
    project_id: str | None = None
    kind: str | None = None
    cursor: str | None = None
    limit: int = 50


@dataclass(frozen=True, slots=True)
class DatasetSearchHit:
    dataset: Dataset
    field_count: int
    reader_count: int
    writer_count: int


@dataclass(frozen=True, slots=True)
class DatasetSearchPage:
    items: tuple[DatasetSearchHit, ...] = ()
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class DatasetDetails:
    dataset: Dataset
    freshness: Freshness
    fields: tuple[DatasetField, ...] = ()
    connection_ids: tuple[str, ...] = ()


RebuildStatus = Literal["skipped", "ok", "failed"]


@dataclass(frozen=True, slots=True)
class RebuildResult:
    status: RebuildStatus
    projection: ProjectCatalogProjection | None = None
    link_count: int = 0
    error: str | None = None
    port_count: int = 0
    column_count: int = 0


@dataclass(slots=True)
class ReconcileSummary:
    """Итог сверки проекций: счётчики по статусам и усечённые тексты ошибок проектов."""

    total: int = 0
    ok: int = 0
    skipped: int = 0
    failed: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)


SyncStatus = Literal["skipped", "synced", "failed", "no_connection", "unsupported"]


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    status: SyncStatus
    new: int = 0
    missing: int = 0
    type_changed: int = 0
    error: str | None = None
    error_kind: CheckErrorKind | None = None
    fields: tuple[DatasetField, ...] = field(default_factory=tuple)


RefreshStatus = Literal["synced", "failed", "no_connection", "unsupported"]


@dataclass(frozen=True, slots=True)
class RefreshOutcome:
    status: RefreshStatus
    new: int = 0
    missing: int = 0
    type_changed: int = 0
    affected_project_ids: tuple[str, ...] = ()
    error: str | None = None
    error_kind: CheckErrorKind | None = None


@dataclass(frozen=True, slots=True)
class ObservationOutcome:
    """Какие сущности обновлены наблюдением; пустой кортеж означает отсутствие линка."""

    dataset_ids: tuple[str, ...] = ()
    trusted_types: bool = False


@dataclass(frozen=True, slots=True)
class DescriptionsUpdateResult:
    dataset: Dataset
    fields: tuple[DatasetField, ...] = ()
