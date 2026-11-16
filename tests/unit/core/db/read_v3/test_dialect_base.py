from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from core.db.read_v3.dialects.clickhouse import ClickHouseDialect
from core.db.read_v3.dialects.mssql import MssqlDialect
from core.db.read_v3.dialects.oracle import OracleDialect
from core.db.read_v3.dialects.postgres import PostgresDialect
from core.db.read_v3.dialects.sqlite import SqliteDialect
from core.db.read_v3.models import ValueKind


# PostgresDialect stands for the base render_literal; the others override it.
@pytest.mark.parametrize(
    "dialect",
    [PostgresDialect(), ClickHouseDialect(), OracleDialect(), MssqlDialect()],
    ids=lambda dialect: dialect.name,
)
@pytest.mark.parametrize(
    ("numpy_value", "python_value"),
    [
        pytest.param(np.int64(130), 130, id="int64"),
        pytest.param(np.int32(-7), -7, id="int32"),
        pytest.param(np.uint64(2**63 + 5), 2**63 + 5, id="uint64"),
        pytest.param(np.float64(1.25), 1.25, id="float64"),
        pytest.param(np.float32(0.5), 0.5, id="float32"),
        pytest.param(np.bool_(True), True, id="bool_true"),
        pytest.param(np.bool_(False), False, id="bool_false"),
        pytest.param(
            np.datetime64("2024-03-05T06:07:08.123456"),
            datetime(2024, 3, 5, 6, 7, 8, 123456),
            id="datetime64_us",
        ),
        pytest.param(
            np.datetime64("2024-03-05T06:07:08.123456789"),
            datetime(2024, 3, 5, 6, 7, 8, 123456),
            id="datetime64_ns",
        ),
        pytest.param(np.datetime64("NaT"), None, id="datetime64_nat"),
    ],
)
def test_render_literal_renders_numpy_scalars_like_python_values(
    dialect, numpy_value, python_value
) -> None:
    assert dialect.render_literal(numpy_value) == dialect.render_literal(python_value)


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

