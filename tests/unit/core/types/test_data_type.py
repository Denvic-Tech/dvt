from __future__ import annotations

from core.types import DataType


def test_data_type_from_type_maps_oracle_number_with_zero_scale_to_int() -> None:
    assert DataType.from_type("NUMBER(10,0)") == DataType.INT


def test_data_type_from_type_maps_oracle_number_with_fractional_scale_to_float() -> None:
    assert DataType.from_type("NUMBER(18,4)") == DataType.FLOAT


def test_data_type_from_type_maps_oracle_binary_double_to_float() -> None:
    assert DataType.from_type("BINARY_DOUBLE") == DataType.FLOAT


def test_data_type_from_type_maps_oracle_varchar2_to_string() -> None:
    assert DataType.from_type("VARCHAR2") == DataType.STRING


def test_data_type_from_type_maps_oracle_timestamp_to_datetime() -> None:
    assert DataType.from_type("TIMESTAMP") == DataType.DATETIME


def test_data_type_from_type_maps_mssql_uniqueidentifier_to_string() -> None:
    assert DataType.from_type("uniqueidentifier") == DataType.STRING


def test_data_type_from_type_maps_mssql_binary_to_string() -> None:
    assert DataType.from_type("varbinary(16)") == DataType.STRING
