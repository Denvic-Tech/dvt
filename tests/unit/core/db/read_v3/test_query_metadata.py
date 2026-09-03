from __future__ import annotations

from uuid import UUID

from core.db.read_v3.query_metadata import describe_query_columns


class _FakeCursor:
    def __init__(self) -> None:
        self.description = [
            ("table_code", str, None, 128, 128, 0, False),
            ("row_cap", int, None, 10, 10, 0, False),
        ]
        self.executed_sql: list[str] = []

    def execute(self, sql: str) -> None:
        self.executed_sql.append(sql)

    def fetchall(self) -> list[tuple[int, str]]:
        return [
            (56, "int"),
            (167, "varchar"),
            (231, "nvarchar"),
        ]

    def close(self) -> None:
        return None


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def close(self) -> None:
        return None


class _FakeDialect:
    name = "mssql"


class _FakeEngine:
    def __init__(self, cursor: _FakeCursor) -> None:
        self.dialect = _FakeDialect()
        self._cursor = cursor

    def raw_connection(self) -> _FakeConnection:
        return _FakeConnection(self._cursor)


def test_describe_query_columns_handles_pyodbc_python_type_codes_for_mssql() -> None:
    cursor = _FakeCursor()
    engine = _FakeEngine(cursor)

    columns = describe_query_columns(
        engine,
        "SELECT table_code, row_cap FROM demo_meta.raw_export_tables ORDER BY table_code",
    )

    assert columns == [
        ("table_code", "NVARCHAR"),
        ("row_cap", "INT"),
    ]
    assert cursor.executed_sql[0] == (
        "SELECT system_type_id, name FROM sys.types WHERE user_type_id = system_type_id"
    )
    assert "OFFSET 0 ROWS" in cursor.executed_sql[1]


def test_describe_query_columns_supports_top_level_cte_for_mssql() -> None:
    cursor = _FakeCursor()
    engine = _FakeEngine(cursor)

    columns = describe_query_columns(
        engine,
        (
            "WITH base_query AS ("
            "SELECT table_code, row_cap FROM demo_meta.raw_export_tables"
            ") "
            "SELECT table_code, row_cap FROM base_query"
        ),
    )

    assert columns == [
        ("table_code", "NVARCHAR"),
        ("row_cap", "INT"),
    ]
    assert "WITH base_query AS" in cursor.executed_sql[1]
    assert "user_query AS (SELECT table_code AS table_code, row_cap AS row_cap FROM base_query)" in (
        cursor.executed_sql[1]
    )
    assert "SELECT TOP 0 * FROM user_query" in cursor.executed_sql[1]


class _FakeBinaryCursor(_FakeCursor):
    def __init__(self) -> None:
        super().__init__()
        self.description = [
            ("guid_col", UUID, None, 36, 36, 0, False),
            ("bin_col", bytes, None, 16, 16, 0, False),
        ]


def test_describe_query_columns_normalizes_uuid_and_binary_type_codes_for_mssql() -> None:
    cursor = _FakeBinaryCursor()
    engine = _FakeEngine(cursor)

    columns = describe_query_columns(
        engine,
        "SELECT guid_col, bin_col FROM dbo.events ORDER BY guid_col",
    )

    assert columns == [
        ("guid_col", "UNIQUEIDENTIFIER"),
        ("bin_col", "VARBINARY"),
    ]
