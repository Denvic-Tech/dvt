from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .json_utils import JSON_ARRAY_ITEM_TOKEN, build_display_json_path, json_safe


_COLUMN_PREFIX = "column_"
_EXTRA_VALUES_KEY = "_extra_values"
_HEADER_CONFIDENCE_THRESHOLD = 0.75
_ROW_CONSISTENCY_THRESHOLD = 0.8


@dataclass(frozen=True, slots=True)
class TabularMatrixInfo:
    path_tokens: tuple[str, ...]
    header_mode: Literal["header_row", "synthetic"]
    columns: tuple[str, ...]
    row_count: int
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TabularNormalizationResult:
    value: Any
    matrices: tuple[TabularMatrixInfo, ...]


def normalize_tabular_json(value: Any) -> TabularNormalizationResult:
    matrices: list[TabularMatrixInfo] = []
    normalized = _normalize_value(json_safe(value), (), matrices)
    return TabularNormalizationResult(value=normalized, matrices=tuple(matrices))


def _normalize_value(
    value: Any,
    path_tokens: tuple[str, ...],
    matrices: list[TabularMatrixInfo],
) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize_value(item, path_tokens + (str(key),), matrices)
            for key, item in value.items()
        }

    if isinstance(value, list):
        detected = _detect_tabular_matrix(value, path_tokens)
        if detected is not None:
            matrices.append(detected)
            return _materialize_matrix(value, detected, matrices)
        return [
            _normalize_value(item, path_tokens + (JSON_ARRAY_ITEM_TOKEN,), matrices)
            for item in value
        ]

    return value


def _detect_tabular_matrix(
    value: list[Any],
    path_tokens: tuple[str, ...],
) -> TabularMatrixInfo | None:
    if len(value) < 2 or any(not isinstance(item, list) for item in value):
        return None

    rows = [item for item in value if isinstance(item, list)]
    if len(rows) != len(value):
        return None

    non_empty_rows = [row for row in rows if row]
    if len(non_empty_rows) < 2:
        return None

    row_lengths = [len(row) for row in rows]
    length_counts: dict[int, int] = {}
    for length in row_lengths:
        length_counts[length] = length_counts.get(length, 0) + 1
    dominant_length = max(length_counts, key=lambda length: (length_counts[length], length))
    if dominant_length < 2:
        return None

    dominant_matches = sum(1 for length in row_lengths if length == dominant_length)
    row_consistency = dominant_matches / len(row_lengths)
    if row_consistency < _ROW_CONSISTENCY_THRESHOLD:
        return None

    header_mode: Literal["header_row", "synthetic"]
    if _looks_like_header_row(rows[0], dominant_length):
        header_mode = "header_row"
        header_source = rows[0]
        data_rows = rows[1:]
    else:
        header_mode = "synthetic"
        header_source = None
        data_rows = rows

    if not data_rows:
        return None

    columns, warnings = _build_columns(
        header_source=header_source,
        width=dominant_length,
        path_tokens=path_tokens,
    )
    display_path = build_display_json_path(path_tokens)
    if header_mode == "synthetic":
        warnings.append(f"Generated synthetic matrix columns at {display_path}.")
    if any(len(row) < dominant_length for row in data_rows):
        warnings.append(f"Padded short matrix rows with nulls at {display_path}.")
    if any(len(row) > dominant_length for row in data_rows):
        warnings.append(f"Stored extra matrix values in {_EXTRA_VALUES_KEY} at {display_path}.")

    return TabularMatrixInfo(
        path_tokens=path_tokens,
        header_mode=header_mode,
        columns=columns,
        row_count=len(data_rows),
        warnings=tuple(warnings),
    )


def _looks_like_header_row(row: list[Any], dominant_length: int) -> bool:
    if len(row) != dominant_length:
        return False

    string_like = sum(1 for cell in row if isinstance(cell, str) and cell.strip())
    confidence = string_like / len(row) if row else 0.0
    return confidence >= _HEADER_CONFIDENCE_THRESHOLD


def _build_columns(
    *,
    header_source: list[Any] | None,
    width: int,
    path_tokens: tuple[str, ...],
) -> tuple[tuple[str, ...], list[str]]:
    warnings: list[str] = []
    seen: dict[str, int] = {}
    columns: list[str] = []

    for index in range(width):
        base_name = _base_column_name(header_source, index)
        unique_name = _deduplicate_column_name(base_name, seen)
        columns.append(unique_name)

        if unique_name != base_name:
            warnings.append(
                f"Normalized duplicate matrix column name at "
                f"{build_display_json_path(path_tokens)}: {base_name} -> {unique_name}"
            )

    return tuple(columns), warnings


def _base_column_name(header_source: list[Any] | None, index: int) -> str:
    if header_source is None:
        return f"{_COLUMN_PREFIX}{index + 1}"

    raw_value = header_source[index] if index < len(header_source) else None
    if isinstance(raw_value, str):
        candidate = raw_value.strip()
    else:
        candidate = str(raw_value).strip() if raw_value is not None else ""

    if not candidate:
        return f"{_COLUMN_PREFIX}{index + 1}"
    return candidate


def _deduplicate_column_name(name: str, seen: dict[str, int]) -> str:
    occurrence = seen.get(name, 0) + 1
    seen[name] = occurrence
    if occurrence == 1:
        return name
    return f"{name}__{occurrence}"


def _materialize_matrix(
    value: list[Any],
    matrix: TabularMatrixInfo,
    matrices: list[TabularMatrixInfo],
) -> list[dict[str, Any]]:
    rows = value[1:] if matrix.header_mode == "header_row" else value
    materialized_rows: list[dict[str, Any]] = []

    for row in rows:
        record: dict[str, Any] = {}
        for index, column in enumerate(matrix.columns):
            cell_value = row[index] if index < len(row) else None
            record[column] = _normalize_value(
                cell_value,
                matrix.path_tokens + (JSON_ARRAY_ITEM_TOKEN, column),
                matrices,
            )

        if len(row) > len(matrix.columns):
            record[_EXTRA_VALUES_KEY] = [
                _normalize_value(
                    cell_value,
                    matrix.path_tokens + (JSON_ARRAY_ITEM_TOKEN, _EXTRA_VALUES_KEY),
                    matrices,
                )
                for cell_value in row[len(matrix.columns):]
            ]
        materialized_rows.append(record)

    return materialized_rows
