from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from importlib.util import find_spec
from uuid import uuid4

import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.exc import DatabaseError

from core.types import DataType


ALL_SQL_DB_ENGINE_FIXTURES = [
    pytest.param("postgres_test_engine", id="postgres"),
    pytest.param("mysql_test_engine", id="mysql"),
    pytest.param("mssql_test_engine", id="mssql"),
    pytest.param("oracle_test_engine", id="oracle"),
    pytest.param("clickhouse_http_test_engine", id="clickhouse"),
]


@pytest.fixture
def resolved_sql_test_engine(
    request: pytest.FixtureRequest,
) -> sa.Engine:
    engine_fixture = request.param
    skip_if_mssql_driver_missing(engine_fixture)
    return request.getfixturevalue(engine_fixture)

WIDE_COLUMNS = [
    "id",
    "str_col",
    "int_col",
    "float_col",
    "dec_col",
    "bool_col",
    "dt_col",
    "date_col",
]

NULLABLE_COLUMNS = [
    "str_col",
    "int_col",
    "float_col",
    "dec_col",
    "bool_col",
    "dt_col",
    "date_col",
]

EXPECTED_WIDE_TYPES_BY_FAMILY: dict[str, dict[str, DataType]] = {
    "postgres": {
        "id": DataType.INT,
        "str_col": DataType.STRING,
        "int_col": DataType.INT,
        "float_col": DataType.FLOAT,
        "dec_col": DataType.FLOAT,
        "bool_col": DataType.BOOLEAN,
        "dt_col": DataType.DATETIME,
        "date_col": DataType.DATETIME,
    },
    "mysql": {
        "id": DataType.INT,
        "str_col": DataType.STRING,
        "int_col": DataType.INT,
        "float_col": DataType.FLOAT,
        "dec_col": DataType.FLOAT,
        "bool_col": DataType.INT,
        "dt_col": DataType.DATETIME,
        "date_col": DataType.DATETIME,
    },
    "clickhouse": {
        "id": DataType.INT,
        "str_col": DataType.STRING,
        "int_col": DataType.INT,
        "float_col": DataType.FLOAT,
        "dec_col": DataType.FLOAT,
        "bool_col": DataType.INT,
        "dt_col": DataType.DATETIME,
        "date_col": DataType.DATETIME,
    },
    "mssql": {
        "id": DataType.INT,
        "str_col": DataType.STRING,
        "int_col": DataType.INT,
        "float_col": DataType.FLOAT,
        "dec_col": DataType.FLOAT,
        "bool_col": DataType.BOOLEAN,
        "dt_col": DataType.DATETIME,
        "date_col": DataType.DATETIME,
    },
    "oracle": {
        "id": DataType.INT,
        "str_col": DataType.STRING,
        "int_col": DataType.INT,
        "float_col": DataType.FLOAT,
        "dec_col": DataType.FLOAT,
        "bool_col": DataType.INT,
        "dt_col": DataType.DATETIME,
        "date_col": DataType.DATETIME,
    },
}


def skip_if_mssql_driver_missing(engine_fixture: str) -> None:
    if engine_fixture == "mssql_test_engine" and find_spec("pyodbc") is None:
        pytest.skip("pyodbc is not installed; MSSQL integration tests are skipped")


def dialect_family(engine: sa.Engine) -> str:
    name = (engine.dialect.name or "").lower()
    if "clickhouse" in name:
        return "clickhouse"
    if "postgres" in name:
        return "postgres"
    if "mysql" in name:
        return "mysql"
    if "mssql" in name or "sqlserver" in name:
        return "mssql"
    if "oracle" in name:
        return "oracle"
    return name


def table_name(prefix: str, engine: sa.Engine) -> str:
    dialect_code = {
        "postgres": "pg",
        "mysql": "my",
        "mssql": "ms",
        "oracle": "or",
        "clickhouse": "ch",
    }.get(dialect_family(engine), "db")
    suffix = uuid4().hex[:8]
    candidate = f"rv3_{prefix}_{dialect_code}_{suffix}"[:30]
    if dialect_family(engine) == "oracle":
        return candidate.upper()
    return candidate


def build_wide_rows(nrows: int = 36) -> list[dict[str, object]]:
    base_dt = datetime(2026, 1, 1, 0, 0, 0)
    base_date = date(2026, 1, 1)
    rows: list[dict[str, object]] = []
    for idx in range(1, nrows + 1):
        rows.append(
            {
                "id": idx,
                "str_col": None if idx % 3 == 0 else f"row_{idx}",
                "int_col": None if idx % 4 == 0 else idx * 10,
                "float_col": None if idx % 5 == 0 else float(idx) * 1.75,
                "dec_col": None if idx % 6 == 0 else (Decimal(idx) / Decimal("3")),
                "bool_col": None if idx % 7 == 0 else (idx % 2 == 0),
                "dt_col": None if idx % 8 == 0 else base_dt + timedelta(minutes=idx),
                "date_col": None if idx % 9 == 0 else base_date + timedelta(days=idx),
            }
        )
    return rows


def build_wide_query(target_table: str, family: str) -> str:
    if family == "mysql":
        select_exprs = [
            "id",
            "CAST(str_col AS CHAR(255)) AS str_col",
            "int_col",
            "float_col",
            "dec_col",
            "bool_col",
            "dt_col",
            "date_col",
        ]
    else:
        select_exprs = list(WIDE_COLUMNS)
    return f"SELECT {', '.join(select_exprs)} FROM {target_table}"


def drop_table(engine: sa.Engine, target_table: str) -> None:
    family = dialect_family(engine)
    with engine.begin() as conn:
        if family == "mssql":
            conn.execute(
                text(
                    f"IF OBJECT_ID(N'{target_table}', N'U') IS NOT NULL DROP TABLE {target_table}"
                )
            )
            return
        if family == "oracle":
            try:
                conn.execute(text(f"DROP TABLE {target_table}"))
            except DatabaseError:
                pass
            return
        conn.execute(text(f"DROP TABLE IF EXISTS {target_table}"))


def create_wide_table(engine: sa.Engine, target_table: str) -> None:
    family = dialect_family(engine)
    with engine.begin() as conn:
        if family == "postgres":
            conn.execute(
                text(
                    f"""
                    CREATE TABLE {target_table} (
                        id INTEGER PRIMARY KEY,
                        str_col TEXT NULL,
                        int_col INTEGER NULL,
                        float_col DOUBLE PRECISION NULL,
                        dec_col NUMERIC(18, 4) NULL,
                        bool_col BOOLEAN NULL,
                        dt_col TIMESTAMP NULL,
                        date_col DATE NULL
                    )
                    """
                )
            )
            return
        if family == "mysql":
            conn.execute(
                text(
                    f"""
                    CREATE TABLE {target_table} (
                        id INT PRIMARY KEY,
                        str_col TEXT NULL,
                        int_col INT NULL,
                        float_col DOUBLE NULL,
                        dec_col DECIMAL(18, 4) NULL,
                        bool_col BOOLEAN NULL,
                        dt_col DATETIME NULL,
                        date_col DATE NULL
                    )
                    """
                )
            )
            return
        if family == "mssql":
            conn.execute(
                text(
                    f"""
                    CREATE TABLE {target_table} (
                        id INT PRIMARY KEY,
                        str_col NVARCHAR(255) NULL,
                        int_col INT NULL,
                        float_col FLOAT NULL,
                        dec_col DECIMAL(18, 4) NULL,
                        bool_col BIT NULL,
                        dt_col DATETIME2 NULL,
                        date_col DATE NULL
                    )
                    """
                )
            )
            return
        if family == "oracle":
            conn.execute(
                text(
                    f"""
                    CREATE TABLE {target_table} (
                        id NUMBER(10) PRIMARY KEY,
                        str_col VARCHAR2(255) NULL,
                        int_col NUMBER(10) NULL,
                        float_col BINARY_DOUBLE NULL,
                        dec_col NUMBER(18, 4) NULL,
                        bool_col NUMBER(1) NULL,
                        dt_col TIMESTAMP NULL,
                        date_col DATE NULL
                    )
                    """
                )
            )
            return
        if family == "clickhouse":
            conn.execute(
                text(
                    f"""
                    CREATE TABLE {target_table} (
                        id Int32,
                        str_col Nullable(String),
                        int_col Nullable(Int32),
                        float_col Nullable(Float64),
                        dec_col Nullable(Decimal(18, 4)),
                        bool_col Nullable(UInt8),
                        dt_col Nullable(DateTime),
                        date_col Nullable(Date)
                    ) ENGINE = Memory
                    """
                )
            )
            return
        raise ValueError(f"Unsupported dialect family: {family}")


def _ch_literal_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def _insert_clickhouse_rows(
    engine: sa.Engine, target_table: str, rows: list[dict[str, object]]
) -> None:
    def _v(row: dict[str, object], key: str) -> str:
        value = row[key]
        if value is None:
            return "NULL"
        if key == "str_col":
            return _ch_literal_string(str(value))
        if key == "int_col":
            return str(int(value))
        if key == "float_col":
            return str(float(value))
        if key == "dec_col":
            return str(Decimal(value))
        if key == "bool_col":
            return "1" if bool(value) else "0"
        if key == "dt_col":
            dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
            return f"toDateTime('{dt.strftime('%Y-%m-%d %H:%M:%S')}')"
        if key == "date_col":
            dv = value if isinstance(value, date) else date.fromisoformat(str(value))
            return f"toDate('{dv.strftime('%Y-%m-%d')}')"
        return _ch_literal_string(str(value))

    values_sql = ", ".join(
        "(" + ", ".join(_v(row, col) for col in WIDE_COLUMNS) + ")" for row in rows
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                f"INSERT INTO {target_table} ({', '.join(WIDE_COLUMNS)}) VALUES {values_sql}"
            )
        )


def insert_rows(engine: sa.Engine, target_table: str, rows: list[dict[str, object]]) -> None:
    family = dialect_family(engine)
    if family == "clickhouse":
        _insert_clickhouse_rows(engine, target_table, rows)
        return

    prepared_rows: list[dict[str, object]] = []
    for row in rows:
        prepared = dict(row)
        if family == "oracle":
            if prepared["bool_col"] is not None:
                prepared["bool_col"] = 1 if bool(prepared["bool_col"]) else 0
        prepared_rows.append(prepared)

    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                INSERT INTO {target_table} (
                    id, str_col, int_col, float_col, dec_col, bool_col, dt_col, date_col
                )
                VALUES (
                    :id, :str_col, :int_col, :float_col, :dec_col, :bool_col, :dt_col, :date_col
                )
                """
            ),
            prepared_rows,
        )


def seed_wide_table(engine: sa.Engine, target_table: str, rows: list[dict[str, object]]) -> None:
    create_wide_table(engine, target_table)
    insert_rows(engine, target_table, rows)


def seed_empty_wide_table(engine: sa.Engine, target_table: str) -> None:
    create_wide_table(engine, target_table)


def assert_wide_result(df: pd.DataFrame, expected_rows: int) -> None:
    col_map = {str(col).lower(): col for col in df.columns}
    missing = [col for col in WIDE_COLUMNS if col not in col_map]
    assert not missing, f"Missing columns in result: {missing}; got: {list(df.columns)}"

    id_col = col_map["id"]
    sorted_df = df.sort_values(id_col).reset_index(drop=True)
    assert len(sorted_df) == expected_rows
    assert sorted_df[id_col].tolist() == list(range(1, expected_rows + 1))

    for nullable_col in NULLABLE_COLUMNS:
        actual_col = col_map[nullable_col]
        null_count = int(sorted_df[actual_col].isna().sum())
        assert null_count > 0, f"Expected nullable values in column '{actual_col}'"
        assert null_count < len(sorted_df), f"Column '{actual_col}' should not be fully NULL"


def dataframe_type_map(df: pd.DataFrame) -> dict[str, DataType]:
    col_map = {str(col).lower(): col for col in df.columns}
    actual_map: dict[str, DataType] = {}
    dtypes_map = df.dtypes.to_dict()
    for logical_name in WIDE_COLUMNS:
        actual_col = col_map[logical_name]
        actual_map[logical_name] = DataType.from_type(dtypes_map[actual_col])
    return actual_map


def assert_strict_wide_types(df: pd.DataFrame, family: str) -> None:
    expected = EXPECTED_WIDE_TYPES_BY_FAMILY[family]
    actual = dataframe_type_map(df)
    assert actual == expected, f"Type map mismatch for dialect '{family}': expected={expected}, actual={actual}"


def assert_wide_meta_non_string_types(meta_df: pd.DataFrame, family: str) -> None:
    expected = EXPECTED_WIDE_TYPES_BY_FAMILY[family]
    actual = dataframe_type_map(meta_df)
    for column, expected_type in expected.items():
        if expected_type == DataType.STRING:
            continue
        assert (
            actual[column] != DataType.STRING
        ), f"Column '{column}' meta dtype degraded to STRING for dialect '{family}': actual={actual}"
