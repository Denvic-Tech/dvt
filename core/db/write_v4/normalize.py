from collections import Counter
from dataclasses import dataclass

import pandas as pd
import sqlalchemy as sa

from core.db.write_v4.errors import WriteV4ExecutionError
from core.db.write_v4.models import MissingColumnsMode, WriteDiagnostic, WriteRequest
from core.utils import is_internal_dvt_name, normalize_index_for_db_write, ru2en


@dataclass
class ColumnAlignment:
    normalized: pd.DataFrame
    insert_column_names: list[str]
    row_count: int
    diagnostics: list[WriteDiagnostic]
    default_only_insert: bool


_NUMERIC_TYPE_PREFIXES = (
    "bigint",
    "decimal",
    "double",
    "float",
    "int",
    "integer",
    "number",
    "numeric",
    "real",
    "smallint",
    "tinyint",
    "uint",
)


def drop_internal_dvt_columns(pdf: pd.DataFrame) -> pd.DataFrame:
    internal_columns = [column for column in pdf.columns if is_internal_dvt_name(column)]
    if not internal_columns:
        return pdf
    return pdf.drop(columns=internal_columns)


def can_omit_table_column(column: sa.Column) -> bool:
    return bool(
        column.nullable
        or column.server_default is not None
        or column.default is not None
        or column.autoincrement is True
        or column.primary_key
    )


def _policy_value(value: object) -> str:
    return getattr(value, "value", str(value))


def _unwrap_type_wrappers(type_name: str) -> str:
    normalized = type_name.strip()
    while True:
        lowered = normalized.lower()
        next_value = None
        for wrapper in ("nullable", "lowcardinality"):
            prefix = f"{wrapper}("
            if lowered.startswith(prefix) and normalized.endswith(")"):
                next_value = normalized[len(prefix):-1].strip()
                break
        if next_value is None:
            return normalized
        normalized = next_value


def _is_numeric_column(column: sa.Column) -> bool:
    normalized = _unwrap_type_wrappers(str(column.type)).lower().replace(" ", "")
    return normalized.startswith(_NUMERIC_TYPE_PREFIXES)


def _raise_non_nullable_numeric_nulls_error(
    table: sa.Table,
    column_names: list[str],
) -> None:
    quoted_columns = ", ".join(repr(column_name) for column_name in column_names)
    if len(column_names) == 1:
        raise WriteV4ExecutionError(
            f"Column {quoted_columns} contains NULL values, but target table "
            f"'{table.fullname}' defines it as a non-nullable numeric column."
        )
    raise WriteV4ExecutionError(
        f"Columns {quoted_columns} contain NULL values, but target table "
        f"'{table.fullname}' defines them as non-nullable numeric columns."
    )


def _case_mismatch_map(
    dataframe_columns: pd.Index,
    table_columns: dict[str, sa.Column],
) -> dict[str, str]:
    dataframe_names = [str(column) for column in dataframe_columns]
    dataframe_lookup = {name.lower(): name for name in dataframe_names}
    mismatches: dict[str, str] = {}
    for table_column in table_columns:
        if table_column in dataframe_names:
            continue
        actual_name = dataframe_lookup.get(table_column.lower())
        if actual_name is None or actual_name == table_column:
            continue
        mismatches[table_column] = actual_name
    return mismatches


def _raise_case_mismatch_error(table: sa.Table, mismatches: dict[str, str]) -> None:
    pairs = ", ".join(
        f"{table_column!r} <- {dataframe_column!r}"
        for table_column, dataframe_column in sorted(mismatches.items())
    )
    raise WriteV4ExecutionError(
        f"DataFrame columns differ from target table '{table.fullname}' only by case: {pairs}. "
        "Exact-case column names are required; rename DataFrame columns to match the table schema."
    )


def _build_declared_rename_map(
    dataframe_names: list[str],
    table_column_names: set[str],
    request: WriteRequest,
) -> dict[str, str]:
    rename_map: dict[str, str] = {}
    for mapping in request.column_mapping or []:
        source_name = str(mapping.source_name)
        target_name = str(mapping.target_name)
        if source_name not in dataframe_names:
            continue
        if target_name not in table_column_names:
            continue
        if source_name != target_name:
            rename_map[source_name] = target_name
    return rename_map


def _build_runtime_rename_map(
    dataframe_columns: pd.Index,
    table: sa.Table,
    request: WriteRequest,
) -> dict[str, str]:
    dataframe_names = [str(column) for column in dataframe_columns]
    table_column_names = {column.name for column in table.columns}
    rename_map = _build_declared_rename_map(dataframe_names, table_column_names, request)

    for source_name in dataframe_names:
        if source_name in rename_map or source_name in table_column_names or source_name.isascii():
            continue
        target_name = ru2en(source_name)
        if not target_name or target_name == source_name or target_name not in table_column_names:
            continue
        rename_map[source_name] = target_name

    resolved_names = [rename_map.get(source_name, source_name) for source_name in dataframe_names]
    duplicate_targets = [name for name, count in Counter(resolved_names).items() if count > 1]
    if not duplicate_targets:
        return rename_map

    duplicate_pairs = ", ".join(
        f"{target_name!r} <- {sorted(source_name for source_name in dataframe_names if rename_map.get(source_name, source_name) == target_name)!r}"
        for target_name in sorted(duplicate_targets)
    )
    raise WriteV4ExecutionError(
        f"DataFrame columns collapse to duplicate target names for table '{table.fullname}': "
        f"{duplicate_pairs}. Rename or remap the DataFrame columns to keep them unique."
    )


def _raise_no_matching_columns_error(
    table: sa.Table,
    dataframe_columns: list[str],
) -> None:
    raise WriteV4ExecutionError(
        f"No DataFrame columns match target table '{table.fullname}'. "
        f"Incoming columns: {sorted(dataframe_columns)!r}. "
        f"Target columns: {[column.name for column in table.columns]!r}."
    )


def align_partition_to_table(
    pdf: pd.DataFrame,
    table: sa.Table,
    request: WriteRequest,
    *,
    include_default_only_diagnostic: bool = True,
) -> ColumnAlignment:
    working = normalize_index_for_db_write(pdf.copy())
    working = drop_internal_dvt_columns(working)
    source_dataframe_columns = [str(column) for column in working.columns]

    table_columns = {column.name: column for column in table.columns}
    rename_map = _build_runtime_rename_map(working.columns, table, request)
    if rename_map:
        working = working.rename(columns=rename_map)

    case_mismatches = _case_mismatch_map(working.columns, table_columns)
    if case_mismatches:
        _raise_case_mismatch_error(table, case_mismatches)

    extra_columns = [column for column in working.columns if column not in table_columns]
    if extra_columns and request.on_extra_df_columns == "error":
        raise WriteV4ExecutionError(
            f"DataFrame contains columns not present in target table '{table.fullname}': {extra_columns!r}"
        )

    if extra_columns:
        working = working.drop(columns=extra_columns)

    if request.mode == "upsert" and request.upsert is not None:
        if request.upsert.key_column not in table_columns:
            raise WriteV4ExecutionError(
                f"Upsert key column '{request.upsert.key_column}' does not exist in target table "
                f"'{table.fullname}'."
            )
        if request.upsert.key_column not in working.columns:
            raise WriteV4ExecutionError(
                f"Upsert key column '{request.upsert.key_column}' must be present in the DataFrame for "
                f"table '{table.fullname}'."
            )

    missing_columns = [column.name for column in table.columns if column.name not in working.columns]
    if missing_columns and request.on_missing_df_columns == "error":
        raise WriteV4ExecutionError(
            f"DataFrame is missing columns required by mismatch policy for table "
            f"'{table.fullname}': {missing_columns!r}"
        )

    if request.on_missing_df_columns == MissingColumnsMode.IGNORE_IF_DEFAULT:
        missing_required = [
            column.name for column in table.columns if column.name in missing_columns and not can_omit_table_column(column)
        ]
        if missing_required:
            raise WriteV4ExecutionError(
                f"DataFrame is missing required columns for table '{table.fullname}': {missing_required!r}"
            )

    insert_column_names = [column.name for column in table.columns if column.name in working.columns]
    if len(working.index) > 0 and source_dataframe_columns and not insert_column_names:
        _raise_no_matching_columns_error(table, source_dataframe_columns)

    normalized = working[insert_column_names].copy()
    non_nullable_numeric_columns = [
        column.name
        for column in table.columns
        if column.name in insert_column_names and not column.nullable and _is_numeric_column(column)
    ]
    if non_nullable_numeric_columns and not normalized.empty:
        nulls_by_column = normalized[non_nullable_numeric_columns].isna().any(axis=0)
        invalid_columns = [
            column_name for column_name, has_nulls in nulls_by_column.items() if bool(has_nulls)
        ]
        if invalid_columns:
            _raise_non_nullable_numeric_nulls_error(table, invalid_columns)
    if insert_column_names:
        normalized = normalized.astype(object).where(pd.notna(normalized), None)

    diagnostics: list[WriteDiagnostic] = []
    if extra_columns and request.on_extra_df_columns == "ignore":
        diagnostics.append(
            WriteDiagnostic(
                code="extra_columns_ignored",
                message="Columns from the DataFrame that do not exist in the target table were ignored.",
                details={"columns": extra_columns},
            )
        )

    if missing_columns and request.on_missing_df_columns != "error":
        diagnostics.append(
            WriteDiagnostic(
                code="missing_columns_ignored",
                message="Columns missing from the DataFrame were omitted from INSERT statements.",
                details={"columns": missing_columns, "policy": _policy_value(request.on_missing_df_columns)},
            )
        )

    default_only_insert = bool(len(working.index) > 0 and not insert_column_names)
    if default_only_insert and include_default_only_diagnostic:
        diagnostics.append(
            WriteDiagnostic(
                code="default_only_insert",
                message="Rows will be inserted without explicit column values.",
                details={"policy": _policy_value(request.on_missing_df_columns)},
            )
        )

    return ColumnAlignment(
        normalized=normalized,
        insert_column_names=insert_column_names,
        row_count=len(working.index),
        diagnostics=diagnostics,
        default_only_insert=default_only_insert,
    )
