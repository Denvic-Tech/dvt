"""Deterministic lazy synthetic data shared by benchmark nodes and the DB seeder.

Every partition is a pure function of ``(schema, PartitionSpec, seed)``: the random generator is
seeded with ``(seed, spec.index)``, so any partition can be regenerated independently and in any
order (for example as a dask ``from_map`` task) with identical content.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pyarrow as pa

SCHEMA_NAMES = ("wide_mixed", "numeric", "wide_text", "dim")
DIALECTS = ("postgres", "clickhouse", "mssql", "mysql")

# Explicit pyarrow storage keeps generated partitions and ``partition_meta`` identical even when
# the process-wide default string storage differs; it equals ``pd.StringDtype()`` / ``"string"``
# whenever pyarrow is installed (always true for DVT runtimes).
STRING_DTYPE = pd.StringDtype(storage="pyarrow")


@dataclass(frozen=True)
class ColumnSpec:
    """One synthetic column: pandas dtype plus the SQL type per dialect.

    ``clickhouse`` already contains ``Nullable(...)`` for nullable columns; other dialects get
    ``NULL`` / ``NOT NULL`` appended from ``nullable``.
    """

    name: str
    dtype: str | pd.api.extensions.ExtensionDtype
    nullable: bool
    postgres: str
    clickhouse: str
    mssql: str
    mysql: str

    def sql_type(self, dialect: str) -> str:
        _check_dialect(dialect)
        return getattr(self, dialect)


_C = ColumnSpec
# fmt: off
SCHEMA_COLUMNS: dict[str, tuple[ColumnSpec, ...]] = {
    "wide_mixed": (
        #  name        dtype             null   postgres            clickhouse
        #                                       mssql            mysql
        _C("id",       "int64",          False, "BIGINT",           "Int64",
                                                "BIGINT",        "BIGINT"),
        _C("int_a",    "int32",          False, "INTEGER",          "Int32",
                                                "INT",           "INT"),
        _C("int_b",    "Int64",          True,  "BIGINT",           "Nullable(Int64)",
                                                "BIGINT",        "BIGINT"),
        _C("float_a",  "float64",        False, "DOUBLE PRECISION", "Float64",
                                                "FLOAT",         "DOUBLE"),
        _C("float_b",  "float64",        False, "DOUBLE PRECISION", "Float64",
                                                "FLOAT",         "DOUBLE"),
        _C("amount",   "float64",        False, "NUMERIC(18,2)",    "Decimal(18, 2)",
                                                "DECIMAL(18,2)", "DECIMAL(18,2)"),
        _C("str_low",  STRING_DTYPE,     False, "VARCHAR(32)",      "LowCardinality(String)",
                                                "NVARCHAR(32)",  "VARCHAR(32)"),
        _C("str_high", STRING_DTYPE,     False, "VARCHAR(32)",      "String",
                                                "NVARCHAR(32)",  "VARCHAR(32)"),
        _C("str_text", STRING_DTYPE,     False, "VARCHAR(128)",     "String",
                                                "NVARCHAR(128)", "VARCHAR(128)"),
        _C("str_null", STRING_DTYPE,     True,  "VARCHAR(64)",      "Nullable(String)",
                                                "NVARCHAR(64)",  "VARCHAR(64)"),
        _C("bool_a",   "bool",           False, "BOOLEAN",          "Bool",
                                                "BIT",           "BOOLEAN"),
        _C("ts_a",     "datetime64[ns]", False, "TIMESTAMP",        "DateTime64(3)",
                                                "DATETIME2(3)",  "DATETIME(3)"),
        _C("date_a",   "datetime64[ns]", False, "DATE",             "Date",
                                                "DATE",          "DATE"),
    ),
    "numeric": (
        _C("id",       "int64",          False, "BIGINT",           "Int64",
                                                "BIGINT",        "BIGINT"),
        _C("value",    "float64",        False, "DOUBLE PRECISION", "Float64",
                                                "FLOAT",         "DOUBLE"),
    ),
    # Few very wide text columns: two Arrow-backed, two Python ``str`` objects.
    "wide_text": (
        _C("id",       "int64",          False, "BIGINT",           "Int64",
                                                "BIGINT",        "BIGINT"),
        _C("text_a",   STRING_DTYPE,     False, "TEXT",             "String",
                                                "NVARCHAR(MAX)", "TEXT"),
        _C("text_b",   STRING_DTYPE,     False, "TEXT",             "String",
                                                "NVARCHAR(MAX)", "TEXT"),
        _C("text_c",   "object",         False, "TEXT",             "String",
                                                "NVARCHAR(MAX)", "TEXT"),
        _C("text_d",   "object",         False, "TEXT",             "String",
                                                "NVARCHAR(MAX)", "TEXT"),
    ),
    # Small lookup table for join benchmarks (one row per ``id``).
    "dim": (
        _C("id",         "int64",        False, "BIGINT",           "Int64",
                                                "BIGINT",        "BIGINT"),
        _C("dim_label",  STRING_DTYPE,   False, "VARCHAR(32)",      "String",
                                                "NVARCHAR(32)",  "VARCHAR(32)"),
        _C("dim_weight", "float64",      False, "DOUBLE PRECISION", "Float64",
                                                "FLOAT",         "DOUBLE"),
    ),
}
# fmt: on
del _C

INT_B_NULL_RATIO = 0.05
STR_NULL_RATIO = 0.10
STR_LOW_CARDINALITY = 20
STR_HIGH_LENGTH = 16
STR_TEXT_LENGTH = 64
STR_NULL_LENGTH = 16
WIDE_TEXT_LENGTH = 2_048
DIM_LABEL_LENGTH = 12

# Optional ``key`` column: ``id * KEY_MULTIPLIER % key_cardinality``. The multiplier is a prime
# larger than any cardinality, so ``rows`` consecutive ids hit every key value
# ``rows // key_cardinality`` or one more times, scattered over all partitions.
KEY_COLUMN = "key"
KEY_MULTIPLIER = 2_654_435_761

# 2020-01-01T00:00:00 .. 2026-01-01T00:00:00 (exclusive), naive UTC.
_TS_START_MS = 1_577_836_800_000
_TS_END_MS = 1_767_225_600_000
_MS_PER_DAY = 86_400_000
_NS_PER_MS = 1_000_000

# 64 CSV/TSV/SQL-safe characters; a 256-entry table maps raw random bytes uniformly onto them.
_ALPHABET = np.frombuffer(
    b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-", dtype=np.uint8
)
_BYTE_TO_CHAR = np.tile(_ALPHABET, 256 // _ALPHABET.size)
_STR_LOW_LABELS = np.array(
    [f"group_{i:02d}".encode("ascii") for i in range(STR_LOW_CARDINALITY)], dtype="S8"
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class PartitionSpec:
    index: int
    id_offset: int
    rows: int


def columns(schema: str) -> tuple[ColumnSpec, ...]:
    _check_schema(schema)
    return SCHEMA_COLUMNS[schema]


def column_names(schema: str) -> list[str]:
    return [column.name for column in columns(schema)]


def partition_plan(rows: int, npartitions: int) -> list[PartitionSpec]:
    """Split ``rows`` into contiguous id ranges; the last partition takes the remainder."""
    if rows < 0:
        raise ValueError(f"rows must be >= 0, got {rows}")
    if npartitions < 1:
        raise ValueError(f"npartitions must be >= 1, got {npartitions}")
    if rows == 0:
        return [PartitionSpec(index=0, id_offset=0, rows=0)]
    npartitions = min(npartitions, rows)
    base = rows // npartitions
    specs = [PartitionSpec(index=i, id_offset=i * base, rows=base) for i in range(npartitions - 1)]
    last_offset = (npartitions - 1) * base
    specs.append(
        PartitionSpec(index=npartitions - 1, id_offset=last_offset, rows=rows - last_offset)
    )
    return specs


def generate_partition(
    schema: str, spec: PartitionSpec, seed: int, key_cardinality: int = 0
) -> pd.DataFrame:
    """Build one partition; pure and deterministic for its arguments.

    ``key_cardinality > 0`` appends the int64 ``key`` column (see ``KEY_MULTIPLIER``); it draws
    no random numbers, so the other columns do not change.
    """
    _check_schema(schema)
    _check_key_cardinality(key_cardinality)
    if spec.rows < 0 or spec.id_offset < 0:
        raise ValueError(f"invalid partition spec: {spec}")
    rng = np.random.default_rng((seed, spec.index))
    n = spec.rows
    ids = np.arange(spec.id_offset, spec.id_offset + n, dtype=np.int64)
    if schema == "numeric":
        data = {"id": ids, "value": rng.standard_normal(n)}
    elif schema == "wide_text":
        data = _wide_text_columns(rng, n, ids)
    elif schema == "dim":
        data = {
            "id": ids,
            "dim_label": _fixed_width_strings(_random_ascii(rng, n, DIM_LABEL_LENGTH), n),
            "dim_weight": rng.random(n),
        }
    else:
        data = _wide_mixed_columns(rng, n, ids)
    if key_cardinality:
        data[KEY_COLUMN] = ids * KEY_MULTIPLIER % key_cardinality
    return pd.DataFrame(data, copy=False)


def partition_meta(schema: str, key_cardinality: int = 0) -> pd.DataFrame:
    """Empty frame with the exact dtypes and index type of ``generate_partition``."""
    _check_key_cardinality(key_cardinality)
    data = {column.name: pd.Series([], dtype=column.dtype) for column in columns(schema)}
    if key_cardinality:
        data[KEY_COLUMN] = pd.Series([], dtype="int64")
    return pd.DataFrame(data)


def quote_identifier(dialect: str, name: str) -> str:
    """Quote a plain identifier (letters, digits, ``_``); anything else is rejected."""
    _check_dialect(dialect)
    if not _IDENTIFIER_RE.match(name):
        raise ValueError(f"unsupported identifier {name!r}: use letters, digits and '_'")
    if dialect == "mssql":
        return f"[{name}]"
    if dialect in ("clickhouse", "mysql"):
        return f"`{name}`"
    return f'"{name}"'


def qualified_table_name(dialect: str, table_name: str, db_schema: str | None = None) -> str:
    parts = [db_schema, table_name] if db_schema else [table_name]
    return ".".join(quote_identifier(dialect, part) for part in parts)


def create_table_sql(
    schema: str, dialect: str, table_name: str, db_schema: str | None = None
) -> list[str]:
    """DDL statements (execute in order) creating the table with ``id`` as primary key.

    For postgres/mssql ``db_schema`` is a schema and is created when missing; for
    clickhouse/mysql it is the database name and must already exist.
    """
    _check_dialect(dialect)
    table = qualified_table_name(dialect, table_name, db_schema)
    definitions = [
        f"{quote_identifier(dialect, column.name)} {_column_type_sql(dialect, column)}"
        for column in columns(schema)
    ]
    statements: list[str] = []
    if db_schema and dialect == "postgres":
        statements.append(f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(dialect, db_schema)}")
    if db_schema and dialect == "mssql":
        # Identifiers are validated by ``quote_identifier`` and cannot contain quotes.
        quoted = quote_identifier(dialect, db_schema)
        statements.append(f"IF SCHEMA_ID(N'{db_schema}') IS NULL EXEC(N'CREATE SCHEMA {quoted}')")
    body = ",\n    ".join(definitions)
    if dialect == "clickhouse":
        statements.append(
            f"CREATE TABLE {table} (\n    {body}\n) ENGINE = MergeTree ORDER BY "
            f"{quote_identifier(dialect, 'id')}"
        )
    else:
        pk = quote_identifier(dialect, "id")
        statements.append(f"CREATE TABLE {table} (\n    {body},\n    PRIMARY KEY ({pk})\n)")
    return statements


def drop_table_sql(dialect: str, table_name: str, db_schema: str | None = None) -> str:
    return f"DROP TABLE IF EXISTS {qualified_table_name(dialect, table_name, db_schema)}"


def _wide_mixed_columns(rng: np.random.Generator, n: int, ids: np.ndarray) -> dict[str, object]:
    # Draw order is part of the determinism contract: do not reorder.
    int_a = rng.integers(0, 1_000_000, size=n, dtype=np.int32)
    int_b_values = rng.integers(-1_000_000_000_000, 1_000_000_000_000, size=n, dtype=np.int64)
    int_b_mask = rng.random(n) < INT_B_NULL_RATIO
    float_a = rng.standard_normal(n)
    float_b = rng.random(n) * 1_000.0
    amount = np.round(rng.random(n) * 100_000.0, 2)
    str_low_codes = rng.integers(0, STR_LOW_CARDINALITY, size=n, dtype=np.int8)
    str_high = _random_ascii(rng, n, STR_HIGH_LENGTH)
    str_text = _random_ascii(rng, n, STR_TEXT_LENGTH)
    str_null_chars = _random_ascii(rng, n, STR_NULL_LENGTH)
    str_null_valid = rng.random(n) >= STR_NULL_RATIO
    bool_a = rng.random(n) < 0.5
    ts_ms = rng.integers(_TS_START_MS, _TS_END_MS, size=n, dtype=np.int64)
    days = rng.integers(_TS_START_MS // _MS_PER_DAY, _TS_END_MS // _MS_PER_DAY, size=n)
    return {
        "id": ids,
        "int_a": int_a,
        "int_b": pd.arrays.IntegerArray(int_b_values, int_b_mask),
        "float_a": float_a,
        "float_b": float_b,
        "amount": amount,
        "str_low": _fixed_width_strings(_STR_LOW_LABELS[str_low_codes].view(np.uint8), n),
        "str_high": _fixed_width_strings(str_high, n),
        "str_text": _fixed_width_strings(str_text, n),
        "str_null": _fixed_width_strings(str_null_chars, n, valid=str_null_valid),
        "bool_a": bool_a,
        "ts_a": (ts_ms * _NS_PER_MS).astype("datetime64[ns]"),
        "date_a": (days.astype(np.int64) * (_MS_PER_DAY * _NS_PER_MS)).astype("datetime64[ns]"),
    }


def _wide_text_columns(rng: np.random.Generator, n: int, ids: np.ndarray) -> dict[str, object]:
    # Draw order is part of the determinism contract: do not reorder.
    data: dict[str, object] = {"id": ids}
    for column in SCHEMA_COLUMNS["wide_text"][1:]:
        values = _fixed_width_strings(_random_ascii(rng, n, WIDE_TEXT_LENGTH), n)
        if column.dtype == "object":
            # An explicit object Series: pandas would infer ``str`` from an object ndarray.
            values = pd.Series(values.to_numpy(dtype=object), dtype=object)
        data[column.name] = values
    return data


def has_object_columns(schema: str) -> bool:
    """Whether ``schema`` has ``object`` columns (dask converts them to strings by default)."""
    return any(column.dtype == "object" for column in columns(schema))


def _random_ascii(rng: np.random.Generator, n: int, length: int) -> np.ndarray:
    """Flat uint8 buffer of ``n * length`` characters drawn from ``_ALPHABET``."""
    raw = np.frombuffer(rng.bytes(n * length), dtype=np.uint8)
    return _BYTE_TO_CHAR[raw]


def _fixed_width_strings(
    chars: np.ndarray, n: int, valid: np.ndarray | None = None
) -> pd.arrays.ArrowStringArray:
    """Zero-copy Arrow string array over a contiguous buffer of equal-length ASCII values."""
    width = chars.size // n if n else 0
    offsets = np.arange(n + 1, dtype=np.int64) * width
    validity = None
    null_count = 0
    if valid is not None:
        null_count = int(n - np.count_nonzero(valid))
        if null_count:
            validity = pa.py_buffer(np.packbits(valid, bitorder="little"))
    array = pa.Array.from_buffers(
        pa.large_string(),
        n,
        [validity, pa.py_buffer(offsets), pa.py_buffer(np.ascontiguousarray(chars))],
        null_count=null_count,
    )
    return pd.arrays.ArrowStringArray(pa.chunked_array([array], type=pa.large_string()))


def _column_type_sql(dialect: str, column: ColumnSpec) -> str:
    sql_type = column.sql_type(dialect)
    if dialect == "clickhouse":
        return sql_type
    return f"{sql_type} {'NULL' if column.nullable else 'NOT NULL'}"


def _check_schema(schema: str) -> None:
    if schema not in SCHEMA_COLUMNS:
        raise ValueError(f"unknown schema {schema!r}; expected one of {SCHEMA_NAMES}")


def _check_key_cardinality(key_cardinality: int) -> None:
    if not 0 <= key_cardinality < KEY_MULTIPLIER:
        raise ValueError(f"key_cardinality must be in [0, {KEY_MULTIPLIER}), got {key_cardinality}")


def _check_dialect(dialect: str) -> None:
    if dialect not in DIALECTS:
        raise ValueError(f"unknown dialect {dialect!r}; expected one of {DIALECTS}")
