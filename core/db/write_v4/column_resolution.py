from collections import Counter
from typing import Literal

import pandas as pd
import sqlalchemy as sa
from pydantic import BaseModel, Field

from core.db.ddl import (
    TableColumnAction,
    TableCreateSpec,
    build_typed_table_preview_from_columns,
    normalize_db_columns_nullable_for_ddl,
    resolve_metadata_schema_for_ddl,
)
from core.db.write_v4.models import (
    ExtraColumnsMode,
    MissingColumnsMode,
    WriteColumnMapping,
    WriteDiagnostic,
)
from core.types import DBColumn, DataFrameMetadata, DataType
from core.utils import is_internal_dvt_name, ru2en


WriteColumnResolutionMode = Literal["existing_table", "typed_create"]
WriteColumnResolutionStatus = Literal[
    "match",
    "explicit_mapping",
    "auto_transliterated",
    "normalized_target",
    "case_resolved",
    "missing_in_db",
    "missing_in_dataframe",
    "type_mismatch",
    "duplicate_effective_target",
    "internal_column_ignored",
    "invalid",
]


class WriteColumnResolutionRow(BaseModel):
    source_name: str | None = None
    requested_target_name: str | None = None
    effective_target_name: str | None = None
    db_name: str | None = None
    dtype: str | None = None
    nullable: bool | None = None
    source_dtype: str | None = None
    db_dtype: str | None = None
    source_nullable: bool | None = None
    db_nullable: bool | None = None
    status: WriteColumnResolutionStatus
    reason: str | None = None
    suggested_action: TableColumnAction | None = None


class WriteColumnResolutionResult(BaseModel):
    effective_column_mapping: list[WriteColumnMapping] = Field(default_factory=list)
    columns: list[WriteColumnResolutionRow] = Field(default_factory=list)
    diagnostics: list[WriteDiagnostic] = Field(default_factory=list)


def resolve_typed_create_write_columns(
    *,
    engine: sa.Engine,
    dataframe_metadata: DataFrameMetadata,
    table_name: str,
    database_name: str | None = None,
    schema_name: str | None = None,
    column_mapping: list[WriteColumnMapping] | None = None,
    table_create_spec: TableCreateSpec | None = None,
) -> WriteColumnResolutionResult:
    source_columns = _dataframe_columns(dataframe_metadata)
    mapping_by_source, diagnostics = _build_mapping_by_source(column_mapping)
    requested_columns: list[DBColumn] = []
    row_inputs: list[tuple[str, str, str | None, bool | None]] = []

    for source_column in source_columns:
        mapping = mapping_by_source.get(source_column.name)
        requested_target_name = mapping.target_name if mapping else source_column.name
        dtype_value = (
            mapping.dtype
            if mapping and mapping.dtype is not None
            else source_column.dtype
        )
        dtype = str(getattr(dtype_value, "value", dtype_value))
        nullable = (
            mapping.nullable
            if mapping and mapping.nullable is not None
            else source_column.nullable
        )
        requested_columns.append(
            DBColumn(
                name=requested_target_name,
                dtype=dtype_value,
                nullable=nullable,
                index=source_column.index,
            )
        )
        row_inputs.append((source_column.name, requested_target_name, dtype, nullable))

    metadata_schema = resolve_metadata_schema_for_ddl(
        dialect_name=engine.dialect.name,
        schema_name=schema_name,
        database_name=database_name,
    )
    normalized_columns = normalize_db_columns_nullable_for_ddl(
        dialect_name=engine.dialect.name,
        columns=requested_columns,
        primary_key_cols=table_create_spec.primary_key_cols if table_create_spec else None,
        preserve_input_nullable=True,
    )
    normalized_nullable_by_requested = {
        column.name: column.nullable for column in normalized_columns
    }

    try:
        table = build_typed_table_preview_from_columns(
            engine=engine,
            table_name=table_name,
            columns=normalized_columns,
            schema_name=metadata_schema,
            spec=table_create_spec,
        )
    except Exception as exc:
        return WriteColumnResolutionResult(
            diagnostics=[
                *diagnostics,
                WriteDiagnostic(
                    code="typed_create_resolution_failed",
                    message="Failed to resolve typed table column names.",
                    details={"error": str(exc)},
                ),
            ]
        )

    rename_map = getattr(table, "rename_map", {})
    rows: list[WriteColumnResolutionRow] = []
    for source_name, requested_target_name, dtype, nullable in row_inputs:
        effective_target_name = rename_map.get(requested_target_name, requested_target_name)
        status: WriteColumnResolutionStatus = (
            "match" if effective_target_name == requested_target_name else "normalized_target"
        )
        reason = None
        if status == "normalized_target":
            reason = "Target name will be normalized by typed table DDL rules."
        rows.append(
            WriteColumnResolutionRow(
                source_name=source_name,
                requested_target_name=requested_target_name,
                effective_target_name=effective_target_name,
                db_name=effective_target_name,
                dtype=dtype,
                nullable=normalized_nullable_by_requested.get(requested_target_name, nullable),
                source_dtype=dtype,
                db_dtype=dtype,
                source_nullable=nullable,
                db_nullable=normalized_nullable_by_requested.get(requested_target_name, nullable),
                status=status,
                reason=reason,
            )
        )

    rows, diagnostics = _mark_duplicate_effective_targets(rows, diagnostics)
    return _build_result(rows=rows, diagnostics=diagnostics)


def resolve_existing_table_write_columns(
    *,
    table: sa.Table,
    dataframe_metadata: DataFrameMetadata,
    column_mapping: list[WriteColumnMapping] | None = None,
    on_extra_df_columns: ExtraColumnsMode = ExtraColumnsMode.IGNORE,
    on_missing_df_columns: MissingColumnsMode = MissingColumnsMode.IGNORE_IF_DEFAULT,
) -> WriteColumnResolutionResult:
    source_columns = _dataframe_columns(dataframe_metadata)
    mapping_by_source, diagnostics = _build_mapping_by_source(column_mapping)
    table_columns = {column.name: column for column in table.columns}
    table_column_names = list(table_columns)
    lower_table_names = _build_unique_lower_name_map(table_column_names)
    rows: list[WriteColumnResolutionRow] = []

    for source_column in source_columns:
        mapping = mapping_by_source.get(source_column.name)
        requested_target_name = mapping.target_name if mapping else source_column.name
        requested_column = _build_requested_db_column(
            source_column=source_column,
            requested_target_name=requested_target_name,
            mapping=mapping,
        )
        row = _resolve_existing_column_row(
            source_name=source_column.name,
            requested_target_name=requested_target_name,
            source_column=requested_column,
            has_explicit_mapping=mapping is not None,
            table_columns=table_columns,
            lower_table_names=lower_table_names,
        )
        rows.append(row)

    rows, diagnostics = _mark_duplicate_effective_targets(rows, diagnostics)
    used_target_names = {
        row.effective_target_name
        for row in rows
        if row.effective_target_name is not None and row.status != "duplicate_effective_target"
    }

    extra_rows = [row for row in rows if row.status == "missing_in_db"]
    if extra_rows and on_extra_df_columns == ExtraColumnsMode.ERROR:
        diagnostics.append(
            WriteDiagnostic(
                code="extra_columns_error",
                message="Some DataFrame columns do not resolve to target table columns.",
                details={"columns": [row.source_name for row in extra_rows]},
            )
        )

    missing_table_names = [
        column_name for column_name in table_column_names if column_name not in used_target_names
    ]
    if missing_table_names:
        diagnostics.append(
            WriteDiagnostic(
                code="missing_columns_ignored",
                message="Some target table columns are not resolved from DataFrame columns.",
                details={
                    "columns": missing_table_names,
                    "policy": _policy_value(on_missing_df_columns),
                },
            )
        )
    if missing_table_names and on_missing_df_columns == MissingColumnsMode.ERROR:
        diagnostics.append(
            WriteDiagnostic(
                code="missing_columns_error",
                message="Some target table columns are missing from the resolved mapping.",
                details={"columns": missing_table_names},
            )
        )

    for column_name in missing_table_names:
        column = table_columns[column_name]
        db_dtype = str(column.type)
        rows.append(
            WriteColumnResolutionRow(
                source_name=None,
                requested_target_name=None,
                effective_target_name=None,
                db_name=column.name,
                dtype=db_dtype,
                nullable=column.nullable,
                source_dtype=None,
                db_dtype=db_dtype,
                source_nullable=None,
                db_nullable=column.nullable,
                status="missing_in_dataframe",
                reason="Target table column is not resolved from any DataFrame column.",
                suggested_action=TableColumnAction(
                    type="drop_column",
                    column_name=column.name,
                ),
            )
        )

    return _build_result(rows=rows, diagnostics=diagnostics)


def _resolve_existing_column_row(
    *,
    source_name: str,
    requested_target_name: str,
    source_column: DBColumn,
    has_explicit_mapping: bool,
    table_columns: dict[str, sa.Column],
    lower_table_names: dict[str, str],
) -> WriteColumnResolutionRow:
    exact = table_columns.get(requested_target_name)
    if exact is not None:
        return _matched_existing_row(
            source_name=source_name,
            requested_target_name=requested_target_name,
            effective_target_name=exact.name,
            column=exact,
            source_column=source_column,
            status="explicit_mapping" if has_explicit_mapping else "match",
            reason="Explicit target name matches the target table."
            if has_explicit_mapping
            else "DataFrame column name matches the target table.",
        )

    if has_explicit_mapping:
        normalized = ru2en(requested_target_name)
        normalized_column = table_columns.get(normalized)
        if normalized != requested_target_name and normalized_column is not None:
            return _matched_existing_row(
                source_name=source_name,
                requested_target_name=requested_target_name,
                effective_target_name=normalized_column.name,
                column=normalized_column,
                source_column=source_column,
                status="normalized_target",
                reason="Explicit target name was normalized to an existing table column.",
            )

        case_resolved = lower_table_names.get(requested_target_name.lower())
        case_column = table_columns.get(case_resolved) if case_resolved else None
        if case_column is not None:
            return _matched_existing_row(
                source_name=source_name,
                requested_target_name=requested_target_name,
                effective_target_name=case_column.name,
                column=case_column,
                source_column=source_column,
                status="case_resolved",
                reason="Explicit target name was resolved to the exact target table case.",
            )

    if not has_explicit_mapping and not source_name.isascii():
        transliterated = ru2en(source_name)
        transliterated_column = table_columns.get(transliterated)
        if transliterated and transliterated_column is not None:
            return _matched_existing_row(
                source_name=source_name,
                requested_target_name=requested_target_name,
                effective_target_name=transliterated_column.name,
                column=transliterated_column,
                source_column=source_column,
                status="auto_transliterated",
                reason="DataFrame column was auto-transliterated to an existing table column.",
            )

    case_resolved = lower_table_names.get(requested_target_name.lower())
    case_column = table_columns.get(case_resolved) if case_resolved else None
    if case_column is not None:
        return _matched_existing_row(
            source_name=source_name,
            requested_target_name=requested_target_name,
            effective_target_name=case_column.name,
            column=case_column,
            source_column=source_column,
            status="case_resolved",
            reason="Column name was resolved to the exact target table case.",
        )

    return WriteColumnResolutionRow(
        source_name=source_name,
        requested_target_name=requested_target_name,
        effective_target_name=None,
        db_name=None,
        dtype=_dtype_to_string(source_column.dtype),
        nullable=source_column.nullable,
        source_dtype=_dtype_to_string(source_column.dtype),
        db_dtype=None,
        source_nullable=source_column.nullable,
        db_nullable=None,
        status="missing_in_db",
        reason="No target table column matches the requested or normalized name.",
        suggested_action=TableColumnAction(
            type="add_column",
            column_name=requested_target_name,
            column=source_column,
        ),
    )


def _matched_existing_row(
    *,
    source_name: str,
    requested_target_name: str,
    effective_target_name: str,
    column: sa.Column,
    source_column: DBColumn,
    status: WriteColumnResolutionStatus,
    reason: str,
) -> WriteColumnResolutionRow:
    source_dtype = _dtype_to_string(source_column.dtype)
    db_dtype = str(column.type)
    source_data_type = _normalize_data_type(source_column.dtype)
    db_data_type = _normalize_data_type(db_dtype)
    is_type_mismatch = (
        source_data_type != DataType.UNKNOWN
        and db_data_type != DataType.UNKNOWN
        and source_data_type != db_data_type
    )

    if is_type_mismatch:
        status = "type_mismatch"
        reason = (
            f"DataFrame column type {source_data_type.value} differs from "
            f"target table column type {db_data_type.value}."
        )

    return WriteColumnResolutionRow(
        source_name=source_name,
        requested_target_name=requested_target_name,
        effective_target_name=effective_target_name,
        db_name=column.name,
        dtype=db_dtype,
        nullable=column.nullable,
        source_dtype=source_dtype,
        db_dtype=db_dtype,
        source_nullable=source_column.nullable,
        db_nullable=column.nullable,
        status=status,
        reason=reason,
        suggested_action=TableColumnAction(
            type="recreate_column",
            column_name=effective_target_name,
            column=source_column.model_copy(update={"name": effective_target_name}),
        )
        if is_type_mismatch
        else None,
    )


def _build_requested_db_column(
    *,
    source_column: DBColumn,
    requested_target_name: str,
    mapping: WriteColumnMapping | None,
) -> DBColumn:
    dtype = mapping.dtype if mapping and mapping.dtype is not None else source_column.dtype
    nullable = (
        mapping.nullable
        if mapping and mapping.nullable is not None
        else source_column.nullable
    )
    return DBColumn(
        name=requested_target_name,
        dtype=dtype,
        dtype_metadata=source_column.dtype_metadata,
        nullable=nullable,
        index=source_column.index,
    )


def _dtype_to_string(dtype: object) -> str:
    value = getattr(dtype, "value", dtype)
    return str(value)


def _normalize_data_type(dtype: object) -> DataType:
    if isinstance(dtype, DataType):
        return dtype
    if isinstance(dtype, str):
        try:
            return DataType(dtype)
        except ValueError:
            return DataType.from_type(dtype)
    return DataType.from_type(dtype)


def _build_result(
    *,
    rows: list[WriteColumnResolutionRow],
    diagnostics: list[WriteDiagnostic],
) -> WriteColumnResolutionResult:
    effective_mapping = [
        WriteColumnMapping(
            source_name=row.source_name,
            target_name=row.effective_target_name,
            dtype=row.dtype,
            nullable=row.nullable,
        )
        for row in rows
        if row.source_name
        and row.effective_target_name
        and row.status
        not in {
            "missing_in_db",
            "missing_in_dataframe",
            "type_mismatch",
            "duplicate_effective_target",
            "invalid",
        }
    ]
    return WriteColumnResolutionResult(
        effective_column_mapping=effective_mapping,
        columns=rows,
        diagnostics=diagnostics,
    )


def _dataframe_columns(dataframe_metadata: DataFrameMetadata) -> list[DBColumn]:
    columns: list[DBColumn] = []
    for column in dataframe_metadata.columns:
        if is_internal_dvt_name(column.name):
            continue
        columns.append(
            DBColumn(
                name=column.name,
                dtype=column.dtype,
                dtype_metadata=column.dtype_metadata,
                nullable=column.nullable,
                index=column.index,
            )
        )
    return columns


def _build_mapping_by_source(
    column_mapping: list[WriteColumnMapping] | None,
) -> tuple[dict[str, WriteColumnMapping], list[WriteDiagnostic]]:
    mapping_by_source: dict[str, WriteColumnMapping] = {}
    duplicate_sources: list[str] = []
    for mapping in column_mapping or []:
        if mapping.source_name in mapping_by_source:
            duplicate_sources.append(mapping.source_name)
            continue
        mapping_by_source[mapping.source_name] = mapping

    diagnostics: list[WriteDiagnostic] = []
    if duplicate_sources:
        diagnostics.append(
            WriteDiagnostic(
                code="duplicate_mapping_sources",
                message="Duplicate source_name values were ignored after their first occurrence.",
                details={"source_names": sorted(set(duplicate_sources))},
            )
        )
    return mapping_by_source, diagnostics


def _build_unique_lower_name_map(names: list[str]) -> dict[str, str]:
    counts = Counter(name.lower() for name in names)
    return {name.lower(): name for name in names if counts[name.lower()] == 1}


def _mark_duplicate_effective_targets(
    rows: list[WriteColumnResolutionRow],
    diagnostics: list[WriteDiagnostic],
) -> tuple[list[WriteColumnResolutionRow], list[WriteDiagnostic]]:
    resolved_names = [
        row.effective_target_name
        for row in rows
        if row.effective_target_name is not None
    ]
    duplicate_names = {
        name
        for name, count in Counter(name.lower() for name in resolved_names).items()
        if count > 1
    }
    if not duplicate_names:
        return rows, diagnostics

    duplicate_effective_targets = [
        row.effective_target_name
        for row in rows
        if row.effective_target_name
        and row.effective_target_name.lower() in duplicate_names
    ]
    marked_rows = [
        row.model_copy(
            update={
                "status": "duplicate_effective_target",
                "reason": "Resolved target name is duplicated by another DataFrame column.",
                "suggested_action": None,
            }
        )
        if row.effective_target_name and row.effective_target_name.lower() in duplicate_names
        else row
        for row in rows
    ]
    diagnostics.append(
        WriteDiagnostic(
            code="duplicate_effective_targets",
            message="Resolved column mapping contains duplicate target names.",
            details={"target_names": sorted(set(duplicate_effective_targets))},
        )
    )
    return marked_rows, diagnostics


def _policy_value(value: object) -> str:
    return getattr(value, "value", str(value))
