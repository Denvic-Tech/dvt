import base64
from datetime import datetime, timezone

import pandas as pd
import pytest

from core.mapper import type_decorators as td


class DialectStub:
    def __init__(self, name: str):
        self.name = name


def test_universal_literal_string_clickhouse_escaping():
    dialect = DialectStub("clickhouse")
    processor = td.UniversalLiteralString().literal_processor(dialect)

    result = processor("a\\b'c")
    assert result == "'a\\\\b\\'c'"


def test_universal_literal_string_standard_escaping():
    dialect = DialectStub("sqlite")
    processor = td.UniversalLiteralString().literal_processor(dialect)

    result = processor("a'b")
    assert result == "'a''b'"


def test_float_with_na():
    decorator = td.FloatWithNA()
    dialect = DialectStub("sqlite")

    assert decorator.process_bind_param(None, dialect) is None
    assert decorator.process_bind_param(float("nan"), dialect) is None
    assert decorator.process_bind_param(1.25, dialect) == 1.25


def test_datetime_with_na():
    decorator = td.DateTimeWithNA()
    dialect = DialectStub("sqlite")

    ts = pd.Timestamp("2024-01-01T10:00:00")
    assert decorator.process_bind_param(ts, dialect) == ts.to_pydatetime()
    assert decorator.process_bind_param(None, dialect) is None

    with pytest.raises(ValueError):
        decorator.process_bind_param("not-a-datetime", dialect)


def test_timedelta_as_float():
    decorator = td.TimedeltaAsFloat()
    dialect = DialectStub("sqlite")

    assert decorator.process_bind_param(pd.Timedelta(days=1), dialect) == 86400.0
    assert decorator.process_bind_param(None, dialect) is None

    with pytest.raises(ValueError):
        decorator.process_bind_param("bad", dialect)


def test_bytes_as_base64_for_clickhouse():
    decorator = td.BytesAsBase64()
    dialect = DialectStub("clickhouse")

    encoded = decorator.process_bind_param(b"data", dialect)
    assert encoded == base64.b64encode(b"data").decode("ascii")

    assert decorator.process_result_value(encoded, dialect) == b"data"

    with pytest.raises(ValueError):
        decorator.process_bind_param("not-bytes", dialect)


def test_bytes_as_base64_for_sqlite():
    decorator = td.BytesAsBase64()
    dialect = DialectStub("sqlite")

    assert decorator.process_bind_param(b"data", dialect) == b"data"
    assert decorator.process_bind_param(None, dialect) is None


def test_json_encoded_type_roundtrip():
    decorator = td.JsonEncodedType()
    dialect = DialectStub("sqlite")

    payload = {"a": 1}
    encoded = decorator.process_bind_param(payload, dialect)
    assert encoded == "{\"a\": 1}"
    assert decorator.process_result_value(encoded, dialect) == payload


def test_integer_with_na():
    decorator = td.IntegerWithNA()
    dialect = DialectStub("sqlite")

    assert decorator.process_bind_param(pd.NA, dialect) is None
    assert decorator.process_bind_param(5, dialect) == 5


def test_boolean_with_na():
    decorator = td.BooleanWithNA()
    dialect = DialectStub("sqlite")

    assert decorator.process_bind_param(pd.NA, dialect) is None
    assert decorator.process_bind_param(True, dialect) is True


def test_ch_datetime_with_na_normalizes_to_utc():
    decorator = td.CHDateTimeWithNA()
    dialect = DialectStub("clickhouse")

    value = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert decorator.process_bind_param(value, dialect) == value
