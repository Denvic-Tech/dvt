from __future__ import annotations

from datetime import UTC, date, datetime, time

import pandas as pd
import pytest
import sqlalchemy as sa

from core.db.read_v3.dialects.mssql import MssqlDialect
from core.db.read_v3.grouping.models import ValueKind as GroupingValueKind
from core.db.read_v3.models import ValueKind
from core.db.read_v3.partitioning.grouping import V3GroupingHelper


def test_mssql_render_literal_datetime_uses_datetime2_cast() -> None:
    dialect = MssqlDialect()
    rendered = dialect.render_literal(datetime(2026, 2, 20, 7, 0, 0))
    assert rendered == "CAST('2026-02-20T07:00:00.000000' AS DATETIME2(6))"


def test_mssql_render_literal_date_uses_date_cast() -> None:
    dialect = MssqlDialect()
    rendered = dialect.render_literal(date(2026, 2, 20))
    assert rendered == "CAST('2026-02-20' AS DATE)"


def test_mssql_render_literal_bit_uses_numeric_boolean() -> None:
    dialect = MssqlDialect()

    assert dialect.render_literal(True) == "1"
    assert dialect.render_literal(False) == "0"


def test_mssql_render_literal_time_uses_time_cast() -> None:
    dialect = MssqlDialect()

    assert dialect.render_literal(time(7, 8, 9, 123456)) == (
        "CAST('07:08:09.123456' AS TIME(6))"
    )


def test_mssql_render_literal_datetimeoffset_preserves_offset() -> None:
    dialect = MssqlDialect()
    value = datetime(2026, 2, 20, 7, 0, 0, tzinfo=UTC)

    assert dialect.render_literal(value) == (
        "CAST('2026-02-20T07:00:00.000000+00:00' AS DATETIMEOFFSET(6))"
    )


@pytest.mark.parametrize(
    ("type_repr", "expected_kind"),
    [
        ("BIT", ValueKind.BOOL),
        ("MONEY", ValueKind.NUMERIC),
        ("SMALLMONEY", ValueKind.NUMERIC),
        ("TIME(7)", ValueKind.STRING),
        ("IMAGE", ValueKind.STRING),
        ("ROWVERSION", ValueKind.STRING),
        ("TIMESTAMP", ValueKind.STRING),
        ("XML", ValueKind.STRING),
        ("SQL_VARIANT", ValueKind.STRING),
        ("HIERARCHYID", ValueKind.STRING),
        ("GEOMETRY", ValueKind.STRING),
        ("GEOGRAPHY", ValueKind.STRING),
        ("VECTOR(3)", ValueKind.STRING),
    ],
)
def test_mssql_detect_value_kind_supports_system_types(
    type_repr: str,
    expected_kind: ValueKind,
) -> None:
    assert MssqlDialect().detect_value_kind(type_repr) == expected_kind


@pytest.mark.parametrize(
    ("type_repr", "source_sql", "expected_sql"),
    [
        (
            "IMAGE",
            "[payload]",
            "CONVERT(VARCHAR(MAX), CONVERT(VARBINARY(MAX), [payload]), 2)",
        ),
        ("ROWVERSION", "[version]", "CONVERT(CHAR(16), [version], 2)"),
        ("TIMESTAMP", "[version]", "CONVERT(CHAR(16), [version], 2)"),
        ("TIME(7)", "[clock]", "CAST([clock] AS NVARCHAR(MAX))"),
        ("XML", "[document]", "CAST([document] AS NVARCHAR(MAX))"),
        ("SQL_VARIANT", "[value]", "CAST([value] AS NVARCHAR(MAX))"),
        ("VECTOR(3)", "[embedding]", "CAST([embedding] AS NVARCHAR(MAX))"),
        ("HIERARCHYID", "[node]", "[node].ToString()"),
        ("GEOMETRY", "[shape]", "[shape].ToString()"),
        ("GEOGRAPHY", "[point]", "[point].ToString()"),
    ],
)
def test_mssql_stringify_output_expr_supports_system_types(
    type_repr: str,
    source_sql: str,
    expected_sql: str,
) -> None:
    assert MssqlDialect().stringify_output_expr(
        source_sql,
        type_repr=type_repr,
    ) == expected_sql


def test_v3_grouping_helper_builds_mssql_safe_datetime_range_sql(monkeypatch) -> None:
    captured_sql: list[str] = []

    def _fake_read_sql_query(sql, *_args, **_kwargs):
        captured_sql.append(str(sql))
        return pd.DataFrame({"cnt": [0]})

    monkeypatch.setattr(
        "core.db.read_v3.partitioning.grouping.read_sql_df",
        lambda _engine, sql: _fake_read_sql_query(sql),
    )

    helper = V3GroupingHelper(
        engine=sa.create_engine("sqlite:///:memory:"),
        dialect=MssqlDialect(),
        relation_sql="FROM [dbo].[users]",
        cte_prefix_sql=None,
        value_kind=GroupingValueKind.DATETIME,
    )
    count = helper.count_range_expr(
        expr_sql="[created_at]",
        start=datetime(2026, 2, 20, 7, 0, 0),
        end=datetime(2026, 2, 20, 8, 0, 0),
        include_end=False,
    )

    assert count == 0
    assert len(captured_sql) == 1
    assert "CAST('2026-02-20T07:00:00.000000' AS DATETIME2(6))" in captured_sql[0]
    assert "CAST('2026-02-20T08:00:00.000000' AS DATETIME2(6))" in captured_sql[0]
