from __future__ import annotations

import posixpath
import unicodedata
from collections.abc import Iterator
from urllib.parse import quote

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc

HIVE_NULL_PARTITION_VALUE = "__HIVE_DEFAULT_PARTITION__"


def validate_partition_columns(partition_on: tuple[str, ...]) -> None:
    """Validate Hive partition column names before any filesystem mutation."""

    duplicates: list[str] = []
    seen: set[str] = set()
    for column in partition_on:
        if column in seen and column not in duplicates:
            duplicates.append(column)
        seen.add(column)
    if duplicates:
        raise ValueError(f"partition_on contains duplicate columns: {duplicates}")

    for column in partition_on:
        if not isinstance(column, str):
            raise TypeError("partition_on column names must be strings.")
        if column == "":
            raise ValueError("partition_on contains an empty column name.")
        if column in {".", ".."}:
            raise ValueError(f"Unsafe Hive partition column name: {column!r}.")
        if any(character in column for character in ("/", "\\", "=", "\x00")):
            raise ValueError(
                f"Unsafe Hive partition column name {column!r}: '/', '\\', '=', and NUL are forbidden."
            )
        if any(unicodedata.category(character) == "Cc" for character in column):
            raise ValueError(
                f"Unsafe Hive partition column name {column!r}: control characters are forbidden."
            )

        normalized = posixpath.normpath(column.replace("\\", "/"))
        if normalized != column or normalized in {".", ".."} or normalized.startswith("../"):
            raise ValueError(
                f"Unsafe Hive partition column name {column!r}: path traversal is forbidden."
            )


def iter_physical_chunks(
    pdf: pd.DataFrame,
    *,
    row_cap: int | None,
    partition_on: tuple[str, ...],
    partition_schema: pa.Schema | None = None,
) -> Iterator[tuple[str, pd.DataFrame]]:
    if partition_on:
        if partition_schema is None:
            raise ValueError("Partition schema is required for Hive partitioned writes.")
        grouper = partition_on[0] if len(partition_on) == 1 else list(partition_on)
        grouped = pdf.groupby(grouper, dropna=False, sort=False, observed=True)
        for keys, group in grouped:
            key_tuple = (keys,) if len(partition_on) == 1 else tuple(keys)
            normalized_values = tuple(
                normalize_partition_value(value, partition_schema.field(column))
                for column, value in zip(partition_on, key_tuple, strict=True)
            )
            relative_dir = "/".join(
                f"{column}={render_hive_partition_value(value, partition_schema.field(column))}"
                for column, value in zip(partition_on, normalized_values, strict=True)
            )
            yield from _split_chunks(group, row_cap=row_cap, relative_dir=relative_dir)
        return
    yield from _split_chunks(pdf, row_cap=row_cap, relative_dir="")


def normalize_partition_value(value: object, field: pa.Field) -> object | None:
    """Cast one Hive partition scalar to its declared logical Arrow type."""

    if _is_null(value):
        return None

    target_type = _partition_value_type(field.type)
    try:
        normalized = pc.cast(pa.scalar(value), target_type, safe=True).as_py()
    except (
        pa.ArrowInvalid,
        pa.ArrowNotImplementedError,
        pa.ArrowTypeError,
        TypeError,
        ValueError,
        OverflowError,
    ) as exc:
        raise ValueError(
            f"Cannot write Hive partition value {value!r} for column '{field.name}' as {field.type}."
        ) from exc

    if normalized == HIVE_NULL_PARTITION_VALUE:
        raise ValueError(
            f"Hive partition value '{HIVE_NULL_PARTITION_VALUE}' is reserved for NULL values "
            "and cannot be written literally."
        )
    return normalized


def render_hive_partition_value(value: object | None, field: pa.Field) -> str:
    if value is None:
        return HIVE_NULL_PARTITION_VALUE

    target_type = _partition_value_type(field.type)
    scalar = pa.scalar(value, type=target_type)
    try:
        rendered = pc.cast(scalar, pa.string(), safe=True).as_py()
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError, pa.ArrowTypeError) as exc:
        raise ValueError(
            f"Cannot render Hive partition value {value!r} for column '{field.name}' as {field.type}."
        ) from exc
    if rendered == HIVE_NULL_PARTITION_VALUE:
        raise ValueError(
            f"Hive partition value '{HIVE_NULL_PARTITION_VALUE}' is reserved for NULL values "
            "and cannot be written literally."
        )
    return quote(rendered, safe="")


def partition_value_type(data_type: pa.DataType) -> pa.DataType:
    """Return the scalar value type represented by a partition field."""

    return _partition_value_type(data_type)


def _partition_value_type(data_type: pa.DataType) -> pa.DataType:
    while pa.types.is_dictionary(data_type):
        data_type = data_type.value_type
    return data_type


def _is_null(value: object) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _split_chunks(
    pdf: pd.DataFrame,
    *,
    row_cap: int | None,
    relative_dir: str,
) -> Iterator[tuple[str, pd.DataFrame]]:
    if row_cap is None:
        if len(pdf) > 0:
            yield relative_dir, pdf
        return
    cap = int(row_cap)
    for start in range(0, len(pdf), cap):
        yield relative_dir, pdf.iloc[start : start + cap]
