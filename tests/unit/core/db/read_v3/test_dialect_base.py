from __future__ import annotations

from core.db.read_v3.dialects.sqlite import SqliteDialect
from core.db.read_v3.models import ValueKind


def test_detect_value_kind_unwraps_nullable_date() -> None:
    dialect = SqliteDialect()
    assert dialect.detect_value_kind("Nullable(Date)") == ValueKind.DATE


def test_detect_value_kind_unwraps_nested_lowcardinality_nullable_string() -> None:
    dialect = SqliteDialect()
    assert (
        dialect.detect_value_kind("LowCardinality(Nullable(String))")
        == ValueKind.STRING
    )


def test_detect_value_kind_detects_jsonb() -> None:
    dialect = SqliteDialect()
    assert dialect.detect_value_kind("JSONB") == ValueKind.JSON


def test_detect_value_kind_detects_uniqueidentifier_as_uuid() -> None:
    dialect = SqliteDialect()
    assert dialect.detect_value_kind("UNIQUEIDENTIFIER") == ValueKind.UUID


def test_detect_value_kind_detects_varbinary_as_string() -> None:
    dialect = SqliteDialect()
    assert dialect.detect_value_kind("VARBINARY(16)") == ValueKind.STRING

