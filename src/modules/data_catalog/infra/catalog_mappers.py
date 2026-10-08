"""ORM <-> domain для каталожных сущностей (отдельно от DataFrame-маппера схемы)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..domain import (
    CheckErrorKind,
    Dataset,
    DatasetConnection,
    DatasetField,
    DatasetLink,
    DiagnosticReason,
    FieldStatus,
    LinkDirection,
    LinkKind,
    PhysicalLocator,
    ProjectCatalogProjection,
    ProjectionDiagnostic,
    ProjectionStamp,
    ProjectionStatus,
    ResolvedVia,
)
from .db_models import (
    DatasetConnectionRecord,
    DatasetFieldRecord,
    DatasetLinkRecord,
    DatasetRecord,
    ProjectCatalogProjectionRecord,
)


def aware(value: datetime | None) -> datetime | None:
    """SQLite возвращает наивные datetime; считаем их UTC."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def dataset_to_domain(record: DatasetRecord) -> Dataset:
    return Dataset(
        id=record.id,
        organization_id=record.organization_id,
        locator=PhysicalLocator(
            dialect=record.dialect,
            host=record.host,
            port=record.port,
            database=record.database,
            schema=record.schema_name,
            table=record.table,
        ),
        physical_key=record.physical_key,
        created_at=aware(record.created_at),
        updated_at=aware(record.updated_at),
        description=record.description,
        schema_synced_at=aware(record.schema_synced_at),
        last_check_failed_at=aware(record.last_check_failed_at),
        description_updated_by=record.description_updated_by,
        description_updated_at=aware(record.description_updated_at),
        observed_at_run=aware(record.observed_at_run),
        last_check_error=record.last_check_error,
        last_check_error_kind=(
            CheckErrorKind(record.last_check_error_kind) if record.last_check_error_kind else None
        ),
    )


def dataset_to_record(dataset: Dataset) -> DatasetRecord:
    record = DatasetRecord(id=dataset.id, organization_id=dataset.organization_id)
    apply_dataset(record, dataset)
    return record


def apply_dataset(record: DatasetRecord, dataset: Dataset) -> DatasetRecord:
    record.organization_id = dataset.organization_id
    record.dialect = dataset.locator.dialect
    record.host = dataset.locator.host
    record.port = dataset.locator.port
    record.database = dataset.locator.database
    record.schema_name = dataset.locator.schema
    record.table = dataset.locator.table
    record.physical_key = dataset.physical_key
    record.description = dataset.description
    record.description_updated_by = dataset.description_updated_by
    record.description_updated_at = dataset.description_updated_at
    record.schema_synced_at = dataset.schema_synced_at
    record.last_check_failed_at = dataset.last_check_failed_at
    record.observed_at_run = dataset.observed_at_run
    record.last_check_error = dataset.last_check_error
    record.last_check_error_kind = (
        dataset.last_check_error_kind.value if dataset.last_check_error_kind else None
    )
    record.created_at = dataset.created_at
    record.updated_at = dataset.updated_at
    return record


def field_to_domain(record: DatasetFieldRecord) -> DatasetField:
    return DatasetField(
        id=record.id,
        dataset_id=record.dataset_id,
        name=record.name,
        status=FieldStatus(record.status),
        first_seen_at=aware(record.first_seen_at),
        last_seen_at=aware(record.last_seen_at),
        dtype=record.dtype,
        nullable=record.nullable,
        ordinal=record.ordinal,
        primary_key=bool(record.primary_key),
        source_comment=record.source_comment,
        description=record.description,
        observed_via=tuple(record.observed_via or ()),
        description_updated_by=record.description_updated_by,
        description_updated_at=aware(record.description_updated_at),
    )


def apply_field(record: DatasetFieldRecord, field: DatasetField) -> DatasetFieldRecord:
    record.dataset_id = field.dataset_id
    record.name = field.name
    record.dtype = field.dtype
    record.nullable = field.nullable
    record.ordinal = field.ordinal
    record.primary_key = field.primary_key
    record.source_comment = field.source_comment
    record.description = field.description
    record.description_updated_by = field.description_updated_by
    record.description_updated_at = field.description_updated_at
    record.status = field.status.value
    record.first_seen_at = field.first_seen_at
    record.last_seen_at = field.last_seen_at
    record.observed_via = list(field.observed_via)
    return record


def field_to_record(field: DatasetField) -> DatasetFieldRecord:
    return apply_field(DatasetFieldRecord(id=field.id, dataset_id=field.dataset_id), field)


def connection_to_domain(record: DatasetConnectionRecord) -> DatasetConnection:
    return DatasetConnection(
        dataset_id=record.dataset_id,
        connection_id=record.connection_id,
        connection_revision=record.connection_revision,
        first_seen_at=aware(record.first_seen_at),
        last_seen_at=aware(record.last_seen_at),
    )


def link_to_record(link: DatasetLink) -> DatasetLinkRecord:
    return DatasetLinkRecord(
        id=link.id,
        dataset_id=link.dataset_id,
        project_id=link.project_id,
        organization_id=link.organization_id,
        node_id=link.node_id,
        node_name=link.node_name,
        direction=link.direction.value,
        kind=link.kind.value,
        resolved_via=link.resolved_via.value,
        graph_revision=link.graph_revision,
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


def link_to_domain(record: DatasetLinkRecord) -> DatasetLink:
    return DatasetLink(
        id=record.id,
        dataset_id=record.dataset_id,
        project_id=record.project_id,
        organization_id=record.organization_id,
        node_id=record.node_id,
        node_name=record.node_name,
        direction=LinkDirection(record.direction),
        kind=LinkKind(record.kind),
        resolved_via=ResolvedVia(record.resolved_via),
        graph_revision=record.graph_revision,
        created_at=aware(record.created_at),
        updated_at=aware(record.updated_at),
    )


def diagnostics_to_json(diagnostics: tuple[ProjectionDiagnostic, ...]) -> list[dict[str, Any]]:
    return [
        {
            "node_id": item.node_id,
            "node_name": item.node_name,
            "reason": item.reason.value,
            "detail": item.detail,
        }
        for item in diagnostics
    ]


def diagnostics_from_json(payload: Any) -> tuple[ProjectionDiagnostic, ...]:
    if not isinstance(payload, list):
        return ()
    result: list[ProjectionDiagnostic] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            reason = DiagnosticReason(str(item.get("reason")))
        except ValueError:
            continue
        result.append(
            ProjectionDiagnostic(
                node_id=str(item.get("node_id", "")),
                node_name=str(item.get("node_name", "")),
                reason=reason,
                detail=item.get("detail"),
            )
        )
    return tuple(result)


def projection_to_domain(record: ProjectCatalogProjectionRecord) -> ProjectCatalogProjection:
    return ProjectCatalogProjection(
        project_id=record.project_id,
        organization_id=record.organization_id,
        stamp=ProjectionStamp(
            graph_revision=record.graph_revision,
            variables_fingerprint=record.variables_fingerprint,
            lineage_schema_version=record.lineage_schema_version,
        ),
        built_at=aware(record.built_at),
        status=ProjectionStatus(record.status),
        depends_on_project_variables=bool(record.depends_on_project_variables),
        error=record.error,
        diagnostics=diagnostics_from_json(record.diagnostics),
    )


def apply_projection(
    record: ProjectCatalogProjectionRecord,
    projection: ProjectCatalogProjection,
) -> ProjectCatalogProjectionRecord:
    record.organization_id = projection.organization_id
    record.graph_revision = projection.stamp.graph_revision
    record.variables_fingerprint = projection.stamp.variables_fingerprint
    record.lineage_schema_version = projection.stamp.lineage_schema_version
    record.depends_on_project_variables = projection.depends_on_project_variables
    record.built_at = projection.built_at
    record.status = projection.status.value
    record.error = projection.error
    record.diagnostics = diagnostics_to_json(projection.diagnostics)
    return record
