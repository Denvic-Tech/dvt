from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from core.parquet.write.filesystem import ParquetFilesystem

_DECIMAL_RE = re.compile(
    r"^decimal(?P<bits>128|256)\((?P<p>\d+)\s*,\s*(?P<s>\d+)\)$", re.IGNORECASE
)
_TIMESTAMP_RE = re.compile(
    r"^timestamp\[(?P<unit>s|ms|us|ns)(?:,\s*tz=(?P<tz>[^\]]+))?\]$",
    re.IGNORECASE,
)
_TIME32_RE = re.compile(r"^time32\[(?P<unit>s|ms)\]$", re.IGNORECASE)
_TIME64_RE = re.compile(r"^time64\[(?P<unit>us|ns)\]$", re.IGNORECASE)

DVT_LOGICAL_SCHEMA_KEY = b"DVT:logical_schema:v1"
DVT_PARTITION_COLUMNS_KEY = b"DVT:partition_columns:v1"
DVT_EMPTY_PARTITIONED_DATASET_KEY = b"DVT:empty_partitioned_dataset:v1"


@dataclass(frozen=True, slots=True)
class ParquetDatasetSchema:
    logical: pa.Schema
    physical: pa.Schema
    partition: pa.Schema
    partition_on: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoredParquetDatasetSchema:
    physical: pa.Schema
    logical: pa.Schema | None
    partition_on: tuple[str, ...] | None
    empty_partitioned_dataset: bool = False


def parse_parquet_type(parquet_type: str) -> pa.DataType:
    raw = parquet_type.strip()
    lowered = raw.lower()
    if not lowered:
        raise ValueError("Parquet type cannot be empty.")

    decimal_match = _DECIMAL_RE.fullmatch(lowered)
    if decimal_match:
        precision = int(decimal_match.group("p"))
        scale = int(decimal_match.group("s"))
        if decimal_match.group("bits") == "128":
            return pa.decimal128(precision, scale)
        return pa.decimal256(precision, scale)

    timestamp_match = _TIMESTAMP_RE.fullmatch(raw)
    if timestamp_match:
        return pa.timestamp(timestamp_match.group("unit").lower(), tz=timestamp_match.group("tz"))

    time32_match = _TIME32_RE.fullmatch(lowered)
    if time32_match:
        return pa.time32(time32_match.group("unit"))

    time64_match = _TIME64_RE.fullmatch(lowered)
    if time64_match:
        return pa.time64(time64_match.group("unit"))

    try:
        return pa.type_for_alias(lowered)
    except ValueError as exc:
        raise ValueError(
            f"Unsupported parquet type '{raw}'. Examples: int64, string, timestamp[ns], "
            "timestamp[us, tz=UTC], decimal128(18,2)."
        ) from exc


def build_dataset_schema(
    meta: pd.DataFrame,
    *,
    write_index: bool,
    parquet_types: dict[str, str] | None,
    partition_on: tuple[str, ...] = (),
) -> ParquetDatasetSchema:
    if parquet_types and not isinstance(parquet_types, dict):
        raise TypeError("Input 'parquet_types' must be a dictionary {column_name: parquet_type}.")

    data_columns = set(map(str, meta.columns))
    unknown = sorted(set(parquet_types or ()) - data_columns)
    if unknown:
        raise ValueError(f"Columns from parquet contract do not exist in DataFrame: {unknown}")

    missing_partition_columns = sorted(set(partition_on) - data_columns)
    if missing_partition_columns:
        raise ValueError(
            f"partition_on columns do not exist in DataFrame: {missing_partition_columns}"
        )

    original_index_names = tuple(meta.index.names)
    prepared_meta = _prepare_index_names(meta, write_index=write_index)
    logical = pa.Schema.from_pandas(prepared_meta, preserve_index=write_index)
    logical = _restore_index_logical_names(
        logical,
        original_names=original_index_names,
        prepared_names=tuple(prepared_meta.index.names),
    )
    logical = _apply_type_overrides(logical, parquet_types)

    physical_meta = prepared_meta.drop(columns=list(partition_on), errors="ignore")
    if not write_index and partition_on and len(physical_meta.columns) == 0:
        physical_meta = prepared_meta
    physical = pa.Schema.from_pandas(physical_meta, preserve_index=write_index)
    physical = _restore_index_logical_names(
        physical,
        original_names=original_index_names,
        prepared_names=tuple(prepared_meta.index.names),
    )
    physical = _apply_type_overrides(physical, parquet_types)

    partition = pa.schema([logical.field(column) for column in partition_on])
    physical = _attach_dataset_metadata(
        physical,
        logical_schema=logical,
        partition_on=partition_on,
    )
    return ParquetDatasetSchema(
        logical=logical,
        physical=physical,
        partition=partition,
        partition_on=partition_on,
    )


def build_arrow_schema(
    meta: pd.DataFrame,
    *,
    write_index: bool,
    parquet_types: dict[str, str] | None,
    partition_on: tuple[str, ...] = (),
) -> pa.Schema:
    """Compatibility helper for callers that only need the physical schema."""
    return build_dataset_schema(
        meta,
        write_index=write_index,
        parquet_types=parquet_types,
        partition_on=partition_on,
    ).physical


def table_from_pandas(pdf: pd.DataFrame, schema: pa.Schema, *, write_index: bool) -> pa.Table:
    prepared = _prepare_index_names_from_schema(pdf, schema, write_index=write_index)
    return pa.Table.from_pandas(
        prepared,
        schema=schema,
        preserve_index=write_index,
        safe=True,
    )


def read_file_schema(filesystem: ParquetFilesystem, path: str) -> pa.Schema:
    return read_file_dataset_schema(filesystem, path).physical


def read_file_dataset_schema(
    filesystem: ParquetFilesystem,
    path: str,
) -> StoredParquetDatasetSchema:
    with filesystem.open(path, "rb") as handle:
        schema = pq.ParquetFile(handle).schema_arrow
    return stored_dataset_schema_from_arrow(schema)


def stored_dataset_schema_from_arrow(schema: pa.Schema) -> StoredParquetDatasetSchema:
    metadata = schema.metadata or {}
    logical_payload = metadata.get(DVT_LOGICAL_SCHEMA_KEY)
    partition_payload = metadata.get(DVT_PARTITION_COLUMNS_KEY)
    empty_partitioned_payload = metadata.get(DVT_EMPTY_PARTITIONED_DATASET_KEY)

    logical = None
    if logical_payload:
        logical = pa.ipc.read_schema(
            pa.BufferReader(base64.b64decode(logical_payload))
        )

    partition_on = None
    if partition_payload:
        decoded = json.loads(partition_payload.decode("utf-8"))
        if not isinstance(decoded, list) or not all(isinstance(value, str) for value in decoded):
            raise ValueError("Invalid DVT Parquet partition metadata.")
        partition_on = tuple(decoded)

    return StoredParquetDatasetSchema(
        physical=schema,
        logical=logical,
        partition_on=partition_on,
        empty_partitioned_dataset=empty_partitioned_payload == b"1",
    )


def ensure_append_dataset_compatible(
    expected: ParquetDatasetSchema,
    actual: StoredParquetDatasetSchema,
    *,
    path: str,
) -> None:
    if not actual.empty_partitioned_dataset:
        ensure_append_schema_compatible(expected.physical, actual.physical, path=path)

    if actual.logical is None or actual.partition_on is None:
        if expected.partition_on:
            raise ValueError(
                "Cannot append Parquet data because an existing physical file does not contain "
                f"DVT logical partition schema metadata: {path}."
            )
        return

    if actual.partition_on != expected.partition_on:
        raise ValueError(
            "Cannot append Parquet data because partition columns do not match the existing "
            f"dataset. Expected {expected.partition_on}, existing {actual.partition_on} in {path}."
        )
    if not expected.logical.equals(actual.logical, check_metadata=False):
        raise ValueError(
            "Cannot append Parquet data because logical schema does not match the existing "
            f"dataset in {path}. Expected {expected.logical.remove_metadata()}, "
            f"existing {actual.logical.remove_metadata()}."
        )


def ensure_append_schema_compatible(
    expected: pa.Schema,
    actual: pa.Schema,
    *,
    path: str | None = None,
) -> None:
    if expected.equals(actual, check_metadata=False):
        return
    location = f" in {path}" if path else ""
    raise ValueError(
        "Cannot append Parquet data because schema does not match the existing dataset"
        f"{location}. Expected {expected.remove_metadata()}, existing {actual.remove_metadata()}."
    )


def _apply_type_overrides(
    schema: pa.Schema,
    parquet_types: dict[str, str] | None,
) -> pa.Schema:
    if not parquet_types:
        return schema
    fields: list[pa.Field] = []
    for field in schema:
        override = parquet_types.get(field.name)
        fields.append(
            field
            if override is None
            else pa.field(
                field.name,
                parse_parquet_type(override),
                nullable=field.nullable,
                metadata=field.metadata,
            )
        )
    return pa.schema(fields, metadata=schema.metadata)


def build_empty_partitioned_sentinel_schema(dataset_schema: ParquetDatasetSchema) -> pa.Schema:
    schema = _attach_dataset_metadata(
        dataset_schema.logical,
        logical_schema=dataset_schema.logical,
        partition_on=dataset_schema.partition_on,
    )
    metadata = dict(schema.metadata or {})
    metadata[DVT_EMPTY_PARTITIONED_DATASET_KEY] = b"1"
    return schema.with_metadata(metadata)


def _attach_dataset_metadata(
    schema: pa.Schema,
    *,
    logical_schema: pa.Schema,
    partition_on: tuple[str, ...],
) -> pa.Schema:
    metadata = dict(schema.metadata or {})
    metadata[DVT_LOGICAL_SCHEMA_KEY] = base64.b64encode(logical_schema.serialize().to_pybytes())
    metadata[DVT_PARTITION_COLUMNS_KEY] = json.dumps(
        list(partition_on), separators=(",", ":")
    ).encode("utf-8")
    return schema.with_metadata(metadata)


def _prepare_index_names(meta: pd.DataFrame, *, write_index: bool) -> pd.DataFrame:
    if not write_index:
        return meta
    prepared = meta.copy(deep=False)
    used = set(map(str, prepared.columns))
    names: list[str] = []
    for level, raw_name in enumerate(prepared.index.names):
        candidate = str(raw_name) if raw_name is not None else f"__index_level_{level}__"
        if candidate in used or candidate in names:
            candidate = _unique_index_name(level, used | set(names))
        names.append(candidate)
    prepared.index = (
        prepared.index.rename(names[0])
        if prepared.index.nlevels == 1
        else prepared.index.set_names(names)
    )
    return prepared


def _prepare_index_names_from_schema(
    pdf: pd.DataFrame,
    schema: pa.Schema,
    *,
    write_index: bool,
) -> pd.DataFrame:
    if not write_index:
        return pdf
    metadata = schema.metadata or {}
    pandas_metadata = metadata.get(b"pandas")
    if not pandas_metadata:
        return _prepare_index_names(pdf, write_index=True)
    payload = json.loads(pandas_metadata.decode("utf-8"))
    index_columns = payload.get("index_columns") or []
    names = [value for value in index_columns if isinstance(value, str)]
    if len(names) != pdf.index.nlevels:
        return _prepare_index_names(pdf, write_index=True)
    prepared = pdf.copy(deep=False)
    prepared.index = (
        prepared.index.rename(names[0])
        if prepared.index.nlevels == 1
        else prepared.index.set_names(names)
    )
    return prepared


def _unique_index_name(level: int, used: set[str]) -> str:
    base = f"__dvt_index_level_{level}__"
    candidate = base
    suffix = 1
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def _restore_index_logical_names(
    schema: pa.Schema,
    *,
    original_names: tuple[object, ...],
    prepared_names: tuple[object, ...],
) -> pa.Schema:
    metadata = dict(schema.metadata or {})
    pandas_metadata = metadata.get(b"pandas")
    if not pandas_metadata or original_names == prepared_names:
        return schema

    payload = json.loads(pandas_metadata.decode("utf-8"))
    original_by_field = {
        prepared: original
        for original, prepared in zip(original_names, prepared_names, strict=True)
    }
    for column in payload.get("columns", []):
        field_name = column.get("field_name")
        if field_name in original_by_field:
            column["name"] = original_by_field[field_name]
    metadata[b"pandas"] = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return schema.with_metadata(metadata)
