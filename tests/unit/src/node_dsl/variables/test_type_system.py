from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from core.types import DataType

from src.node_dsl import IO
from src.node_dsl.variables.type_system import (
    coerce_scalar_variable_value,
    ensure_expression_supported_variable_type,
    get_variable_scalar_type_values,
    infer_variable_scalar_type_from_annotation,
    infer_variable_scalar_type_from_data_type,
    infer_variable_scalar_type_from_metadata_type,
    infer_variable_scalar_type_from_value,
    normalize_variable_scalar_type,
)


def test_normalize_variable_scalar_type_accepts_io_and_string() -> None:
    assert normalize_variable_scalar_type(IO.STRING) == IO.STRING
    assert normalize_variable_scalar_type("FLOAT") == IO.FLOAT


def test_normalize_variable_scalar_type_rejects_non_scalar_io() -> None:
    with pytest.raises(ValueError, match="Unsupported variable type"):
        normalize_variable_scalar_type(IO.DATAFRAME)


def test_coerce_scalar_variable_value_supports_datetime_and_timedelta() -> None:
    assert coerce_scalar_variable_value("2026-04-01T10:20:30", IO.DATETIME) == datetime(
        2026, 4, 1, 10, 20, 30
    )
    assert coerce_scalar_variable_value("1d 2h", IO.TIMEDELTA) == timedelta(days=1, hours=2)


def test_coerce_scalar_variable_value_rejects_bool_for_int() -> None:
    with pytest.raises(ValueError, match="must not be boolean"):
        coerce_scalar_variable_value(True, IO.INT)


def test_infer_variable_scalar_type_helpers_cover_value_data_type_and_metadata() -> None:
    assert infer_variable_scalar_type_from_value({"key": "value"}) == IO.JSON
    assert infer_variable_scalar_type_from_data_type(DataType.CATEGORY) == IO.STRING
    assert infer_variable_scalar_type_from_metadata_type("jsonb") == IO.JSON
    assert infer_variable_scalar_type_from_metadata_type("bigint") == IO.INT


def test_infer_variable_scalar_type_from_annotation_supports_optional_and_json() -> None:
    assert infer_variable_scalar_type_from_annotation(int | None) == IO.INT
    assert infer_variable_scalar_type_from_annotation(dict[str, str] | list[str]) == IO.JSON


def test_get_variable_scalar_type_values_matches_expected_public_scalar_types() -> None:
    assert get_variable_scalar_type_values() == (
        "STRING",
        "BOOLEAN",
        "INT",
        "FLOAT",
        "DATETIME",
        "TIMEDELTA",
        "JSON",
    )
