from __future__ import annotations

from typing import ForwardRef, Optional

from src.modules.data_catalog.domain import TableSchema
from src.node_dsl import IO
from src.node_dsl.type_resolver import TypeResolver


def test_type_resolver_accepts_direct_io_string_name() -> None:
    resolved = TypeResolver().resolve("STRING")

    assert resolved.io_type == IO.STRING
    assert resolved.is_list_type is False


def test_type_resolver_accepts_forward_ref_with_io_value() -> None:
    resolved = TypeResolver().resolve(ForwardRef("STRING"))

    assert resolved.io_type == IO.STRING
    assert resolved.is_list_type is False


def test_io_equality_is_exact_for_distinct_members() -> None:
    assert IO.STRING != IO.VARIABLE
    assert IO.INT != IO.FLOAT
    assert IO.SIGNAL != IO.VARIABLE


def test_type_resolver_treats_plain_string_dict_as_schema() -> None:
    resolved = TypeResolver().resolve(dict[str, str])

    assert resolved.io_type == IO.SCHEMA
    assert resolved.is_optional is False
    assert resolved.schema == {
        "type": "object",
        "additionalProperties": {"type": "string"},
        "propertyNames": {"type": "string"},
    }


def test_type_resolver_treats_optional_plain_string_dict_as_optional_schema() -> None:
    resolved = TypeResolver().resolve(Optional[dict[str, str]])

    assert resolved.io_type == IO.SCHEMA
    assert resolved.is_optional is True
    assert resolved.schema == {
        "type": "object",
        "additionalProperties": {"type": "string"},
        "propertyNames": {"type": "string"},
    }


def test_type_resolver_keeps_variable_dict_as_variable() -> None:
    resolved = TypeResolver().resolve(dict[str, IO.VARIABLE])

    assert resolved.io_type == IO.VARIABLE
    assert resolved.is_optional is False


def test_type_resolver_maps_table_schema_to_custom_io_type() -> None:
    resolved = TypeResolver().resolve(TableSchema)

    assert resolved.io_type == IO.TABLE_SCHEMA
    assert resolved.is_optional is False
