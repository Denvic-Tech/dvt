from __future__ import annotations

import logging
import uuid
from collections.abc import Generator
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

import dask
import dask.dataframe as dd
import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
import sqlalchemy as sa

from core.db.write_v4 import UpsertConfig, WriteMode, WriteRequest, WriteTarget, write_dataframe
from core.db.write_v4.errors import WriteV4ExecutionError
from core.db.write_v4.executors.mssql import MssqlWriteExecutor
from core.db.write_v4.executors.sql import SQLWriteExecutor
from core.db.write_v4.resolver import resolve_executor

from services.task_benchmarking import synthetic

pyodbc = pytest.importorskip("pyodbc")

pytestmark = pytest.mark.docker_required

SEED = 42

# Every allow-listed type, fed from the source kinds the conversion matrix accepts, with the edge
# values whose server-side conversion fast_executemany must keep: NULL markers, rounding of
# datetime/smalldatetime/decimal, trailing blanks, non-BMP text, max and 2000+ character columns.
_PARITY_DDL = (
    "id int PRIMARY KEY, b bit, b_int bit, ti tinyint, si smallint, i int, i_float int, "
    "i_str int, bi bigint, r real, f float, f_dec float, de decimal(18,2), "
    "de_float decimal(18,2), nu numeric(10,4), nu_int numeric(10,4), c char(5), vc varchar(20), "
    "vcm varchar(max), nc nchar(5), nvc nvarchar(20), nvc_arrow nvarchar(64), "
    "nvcm nvarchar(max), nv_long nvarchar(3000), d date, d_obj date, dtm datetime, "
    "dtm_date datetime, dt2 datetime2(7), dt2_aware datetime2(7), dt2_arrow_date datetime2(3), "
    "dt2_obj datetime2, dt23 datetime2(3), sdt smalldatetime, dto datetimeoffset(7), "
    "dto_naive datetimeoffset(3), dto_str datetimeoffset, t time(7), t_str time(3), "
    "u uniqueidentifier, u_str uniqueidentifier"
)
_NS = pd.to_datetime(
    [
        "2020-01-01 00:00:00.0000017",
        "1969-12-31 23:59:59.9999995",
        None,
        "2024-02-29 23:30:00",
        "1999-12-31 23:59:59.9995",
        "2020-06-01 12:00:00.0000025",
    ],
    format="ISO8601",
).astype("datetime64[ns]")
_DATES = [
    date(2020, 1, 2),
    None,
    date(1753, 1, 1),
    date(9999, 12, 31),
    date(2024, 2, 29),
    date(1970, 1, 1),
]


def _obj(values) -> pd.Series:
    return pd.Series(values, dtype=object)


def _parity_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": range(6),
            "b": pd.array([True, False, None, True, False, True], dtype="boolean"),
            "b_int": pd.array([1, 0, None, 1, 0, 1], dtype="Int64"),
            "ti": pd.array([0, 255, None, 1, 2, 3], dtype="Int64"),
            "si": np.array([-32768, 32767, 0, 1, 2, 3], dtype="int16"),
            "i": np.array([2**31 - 1, -(2**31), 0, 1, 2, 3], dtype="int32"),
            "i_float": [1.0, 2.7, -2.7, np.nan, 3.0, 1e9],
            "i_str": _obj(["42", " 7 ", None, "-1", "0", "+3"]),
            "bi": np.array([0, 2**63 - 1, -(2**63), 5, 6, 7], dtype="int64"),
            "r": np.array([0.1, 1 / 3, 3.4e38, np.nan, -0.0, 16777217.0], dtype="float32"),
            "f": [0.1, 1 / 3, 1e300, 2.2250738585072014e-308, -0.0, np.nan],
            "f_dec": _obj(
                [Decimal("0.1"), Decimal("1E+2"), None, Decimal("-123.456"), Decimal("0"), None]
            ),
            "de": _obj(
                [
                    Decimal("1.005"),
                    Decimal("-0.0005"),
                    Decimal("1234567890123456.78"),
                    None,
                    Decimal("0"),
                    Decimal("1E+2"),
                ]
            ),
            "de_float": [1.005, 2.675, 0.1 + 0.2, np.nan, 1e-4, 76577.65],
            "nu": pd.array(
                [
                    Decimal("1.00005"),
                    Decimal("-2.00015"),
                    None,
                    Decimal("0"),
                    Decimal("12345.6789"),
                    Decimal("99999.99994"),
                ],
                dtype=pd.ArrowDtype(pa.decimal128(12, 5)),
            ),
            "nu_int": pd.array([1, -2, None, 0, 999999, 5], dtype="Int64"),
            "c": _obj(["ab", "", None, "abcde  ", "x", "é"]),
            "vc": _obj(["a", " lead", "trail ", None, "é" * 15, "Привет"]),
            "vcm": _obj(["x" * 9000, "", None, "y", "z" * 8001, "é"]),
            "nc": _obj(["ab", "\U0001f600", None, "", "abcde", "ж"]),
            "nvc": _obj(["", "Привет \U0001f600", None, "x" * 20, "\U0001f600" * 10, "tab\t"]),
            "nvc_arrow": pd.array(
                ["a", None, "б", "", "\U0001f600", "z"], dtype=pd.ArrowDtype(pa.large_string())
            ),
            "nvcm": _obj(["ж" * 5000, None, "\U0001f600" * 3000, "", "a", "b"]),
            "nv_long": _obj(["q" * 2500, None, "", "a", "b", "c"]),
            "d": _NS,
            "d_obj": _obj(
                [
                    date(2020, 1, 2),
                    None,
                    date(1, 1, 1),
                    date(9999, 12, 31),
                    date(2024, 2, 29),
                    date(1970, 1, 1),
                ]
            ),
            "dtm": pd.to_datetime(
                [
                    "2020-01-01 23:59:59.9985",
                    "1999-12-31 23:59:59.995",
                    None,
                    "1753-01-01",
                    "2020-01-01 10:00:00.1234567",
                    "2024-02-29 12:00:00.0015",
                ],
                format="ISO8601",
            ).astype("datetime64[ns]"),
            "dtm_date": _obj(_DATES),
            "dt2": _NS,
            "dt2_aware": _NS.tz_localize("Europe/Moscow"),
            "dt2_arrow_date": pd.array(_DATES, dtype=pd.ArrowDtype(pa.date32())),
            "dt2_obj": _obj(
                [
                    datetime(2020, 1, 2, 3, 4, 5, 678901),
                    None,
                    datetime(1, 1, 1),
                    datetime(2262, 1, 1, 0, 0, 0, 1),
                    datetime(1900, 1, 1),
                    datetime(2000, 1, 1, 0, 0, 0, 999999),
                ]
            ),
            "dt23": _NS,
            "sdt": pd.to_datetime(
                [
                    "2020-01-01 10:00:29.999",
                    "2020-01-01 10:00:30.000",
                    None,
                    "1900-01-01",
                    "2079-06-06 23:59:00",
                    "2020-01-01 23:59:59.999",
                ],
                format="ISO8601",
            ),
            "dto": _NS.tz_localize("UTC").tz_convert("Asia/Kolkata"),
            "dto_naive": _NS,
            "dto_str": _obj(
                [
                    "2020-01-01 10:00:00 +05:00",
                    None,
                    "2020-01-01T10:00:00Z",
                    "2020-01-01",
                    "2020-01-01 10:00:00.1234567 -03:30",
                    "1999-12-31",
                ]
            ),
            "t": _obj(
                [
                    time(1, 2, 3, 4),
                    None,
                    time(23, 59, 59, 999999),
                    time(0, 0),
                    time(12, 0, 0, 500),
                    time(1),
                ]
            ),
            "t_str": _obj(["01:02:03.0045", None, "23:59:59.9999", "00:00", "12:00:00", "1:2:3"]),
            "u": _obj([uuid.UUID(int=i) for i in range(5)] + [None]),
            "u_str": _obj(
                [
                    "{00000000-0000-0000-0000-000000000002}",
                    "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12",
                    None,
                    "A0EEBC99-9C0B-4EF8-BB6D-6BB9BD380A11",
                    None,
                    "00000000-0000-0000-0000-000000000001",
                ]
            ),
        }
    )


@pytest.fixture(scope="module")
def ms_engine(mssql_container) -> Generator[sa.Engine]:
    drivers = [driver for driver in pyodbc.drivers() if "ODBC Driver" in driver]
    if not drivers:
        pytest.skip("Microsoft ODBC driver is required for MSSQL integration tests")
    url = sa.make_url(mssql_container.get_connection_url()).update_query_dict(
        {"driver": drivers[-1], "TrustServerCertificate": "yes"}
    )
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    database = f"write_v4_ms_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.exec_driver_sql(f"CREATE DATABASE [{database}]")
    engine = sa.create_engine(url.set(database=database))
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.exec_driver_sql(
                f"ALTER DATABASE [{database}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE"
            )
            conn.exec_driver_sql(f"DROP DATABASE [{database}]")
        admin.dispose()


@pytest.fixture
def fast_calls(monkeypatch) -> list[str]:
    """Names of the tables whose partitions were written by a successful fast_executemany."""
    calls: list[str] = []
    original = MssqlWriteExecutor._fast_insert

    def spy(self, table, *args, **kwargs):
        rows = original(self, table, *args, **kwargs)
        calls.append(table.name)
        return rows

    monkeypatch.setattr(MssqlWriteExecutor, "_fast_insert", spy)
    return calls


def _name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _create(engine: sa.Engine, table: str, ddl: str) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(f"CREATE TABLE [{table}] ({ddl})")


def _write(
    engine: sa.Engine, pdf: pd.DataFrame, table: str, *, npartitions: int = 2, **kwargs
) -> int:
    request = WriteRequest(
        target=WriteTarget(table_name=table),
        **{"mode": WriteMode.APPEND, "write_workers": 1, **kwargs},
    )
    # Keep object columns (Decimal, UUID, raw strings) as built: dask would turn them into strings.
    with dask.config.set({"dataframe.convert-string": False}):
        ddf = dd.from_pandas(pdf, npartitions=npartitions, sort=False)
    return write_dataframe(ddf, engine, request).rows_written


def _rows_as_text(engine: sa.Engine, table: str) -> list[tuple]:
    """Rows as exact text: string bytes (no collation folding), floats with 17 digits."""
    with engine.connect() as conn:
        columns = conn.exec_driver_sql(
            "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = ? ORDER BY ORDINAL_POSITION",
            (table,),
        ).all()
        expressions = []
        for name, data_type in columns:
            if data_type in ("char", "varchar", "nchar", "nvarchar"):
                expressions.append(f"CONVERT(varbinary(max), [{name}])")
            elif data_type in ("float", "real"):
                expressions.append(f"CONVERT(varchar(40), [{name}], 3)")
            elif data_type in (
                "date",
                "datetime",
                "datetime2",
                "smalldatetime",
                "datetimeoffset",
                "time",
            ):
                expressions.append(f"CONVERT(nvarchar(60), [{name}], 121)")
            else:
                expressions.append(f"CONVERT(nvarchar(100), [{name}])")
        statement = f"SELECT {', '.join(expressions)} FROM [{table}] ORDER BY [{columns[0][0]}]"
        return [tuple(row) for row in conn.exec_driver_sql(statement)]


def _count(engine: sa.Engine, table: str, where: str = "1 = 1") -> int:
    with engine.connect() as conn:
        return conn.exec_driver_sql(f"SELECT count(*) FROM [{table}] WHERE {where}").scalar_one()


def test_fast_executemany_and_inherited_path_store_identical_values_for_every_type(
    ms_engine: sa.Engine, fast_calls: list[str]
) -> None:
    assert isinstance(resolve_executor(ms_engine), MssqlWriteExecutor)
    via_insert, via_fast = _name("via_insert"), _name("via_fast")
    _create(ms_engine, via_insert, _PARITY_DDL)
    _create(ms_engine, via_fast, _PARITY_DDL)
    pdf = _parity_frame()

    assert _write(ms_engine, pdf, via_insert, mssql_fast_executemany=False) == len(pdf)
    assert fast_calls == []
    assert _write(ms_engine, pdf, via_fast, rows_per_batch=1) == len(pdf)
    assert fast_calls == [via_fast, via_fast]

    expected = _rows_as_text(ms_engine, via_insert)
    assert _rows_as_text(ms_engine, via_fast) == expected
    # Spot checks of the shared server-side semantics (columns in _PARITY_DDL order).
    row0, row1, row3, row5 = expected[0], expected[1], expected[3], expected[5]
    assert row1[13] == "2.67"  # float -> decimal: the binary value of 2.675, rounded by the server
    assert row0[12] == "1.01"  # Decimal 1.005 -> decimal(18,2) rounds half away from zero
    assert row0[26] == "2020-01-02 00:00:00.000"  # datetime rounds 23:59:59.9985 up
    assert row1[28] == "1969-12-31 23:59:59.9999990"  # nanoseconds floored to microseconds
    assert row3[16] == b"abcde"  # trailing blanks above char(5) are trimmed
    assert row5[17] == b"??????"  # non-code-page text into varchar
    assert row0[20] == b""  # empty string stays empty
    assert row0[34] == "2020-01-01 05:30:00.0000010 +05:30"


def test_fast_executemany_handles_append_truncate_and_upsert(
    ms_engine: sa.Engine, fast_calls: list[str]
) -> None:
    events = _name("events")
    _create(ms_engine, events, "id int PRIMARY KEY, name nvarchar(20), amount decimal(10,2)")

    def frame(ids, names, amounts) -> pd.DataFrame:
        return pd.DataFrame({"id": ids, "name": names, "amount": amounts})

    first = frame([1, 2, 3, 4], ["a", "b", None, "d"], [1.005, 2.5, 3.0, None])
    assert _write(ms_engine, first, events) == 4
    assert fast_calls == [events, events]

    upsert = frame([3, 5], ["c2", "e"], [30.0, 50.125])
    written = _write(
        ms_engine, upsert, events, mode=WriteMode.UPSERT, upsert=UpsertConfig(key_column="id")
    )
    assert written == 2
    # Upsert stages through a scratch table: fast_executemany writes into it.
    assert len(fast_calls) == 4
    assert all(name.startswith(events) and name != events for name in fast_calls[2:])
    assert _rows_as_text(ms_engine, events) == [
        ("1", b"a\x00", "1.00"),
        ("2", b"b\x00", "2.50"),
        ("3", b"c\x002\x00", "30.00"),
        ("4", b"d\x00", None),
        ("5", b"e\x00", "50.13"),
    ]

    replacement = frame([10], ["z"], [0.5])
    assert _write(ms_engine, replacement, events, mode=WriteMode.TRUNCATE, npartitions=1) == 1
    assert len(fast_calls) == 5
    assert _rows_as_text(ms_engine, events) == [("10", b"z\x00", "0.50")]


def test_unsupported_types_and_identity_inserts_use_the_inherited_path(
    ms_engine: sa.Engine, fast_calls: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    docs, keyed = _name("docs"), _name("keyed")
    _create(ms_engine, docs, "id int PRIMARY KEY, payload xml, note nvarchar(10)")
    _create(ms_engine, keyed, "id int IDENTITY(1,1) PRIMARY KEY, v int")
    pdf = pd.DataFrame({"id": [1, 2], "payload": _obj(["<a>1</a>", None]), "note": _obj(["x", ""])})

    with caplog.at_level(logging.WARNING, logger="core.db.write_v4.executors.mssql"):
        assert _write(ms_engine, pdf, docs) == 2
        assert _write(ms_engine, pd.DataFrame({"id": [7, 9], "v": [1, 2]}), keyed) == 2
        assert _write(ms_engine, pd.DataFrame({"v": [3]}), keyed, npartitions=1) == 1

    # The identity table takes the fast path once the identity column is not inserted.
    assert fast_calls == [keyed]
    warnings = [r.getMessage() for r in caplog.records if "is not used" in r.getMessage()]
    assert len(warnings) == 2
    assert "payload (xml)" in warnings[0]
    assert "id (int IDENTITY)" in warnings[1]
    assert _rows_as_text(ms_engine, docs) == [("1", "<a>1</a>", b"x\x00"), ("2", None, b"")]
    assert _rows_as_text(ms_engine, keyed) == [("7", "1"), ("9", "2"), ("10", "3")]


def test_partition_without_parity_goes_alone_through_the_inherited_path(
    ms_engine: sa.Engine, fast_calls: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    notes, expected = _name("notes"), _name("notes_insert")
    _create(ms_engine, notes, "id int PRIMARY KEY, note nvarchar(20)")
    _create(ms_engine, expected, "id int PRIMARY KEY, note nvarchar(20)")
    floats = pd.DataFrame({"id": [1, 2], "note": [0.5, 1.25]})
    strings = pd.DataFrame({"id": [3, 4], "note": _obj(["a", None])})

    with caplog.at_level(logging.WARNING, logger="core.db.write_v4.executors.mssql"):
        assert _write(ms_engine, floats, notes, npartitions=1) == 2
        assert _write(ms_engine, strings, notes, npartitions=1) == 2
    for frame in (floats, strings):
        _write(ms_engine, frame, expected, npartitions=1, mssql_fast_executemany=False)

    assert fast_calls == [notes]
    assert any("float values into a nvarchar column" in r.getMessage() for r in caplog.records)
    assert _rows_as_text(ms_engine, notes) == _rows_as_text(ms_engine, expected)


def test_constraint_violation_rolls_back_only_its_partition(ms_engine: sa.Engine) -> None:
    keys = _name("keys")
    _create(ms_engine, keys, "id int PRIMARY KEY, v int")
    # Partition 1: ids 0..4. Partition 2: ids 5, 6, 5, 8, 9 -> duplicate key at its row 3.
    pdf = pd.DataFrame({"id": [0, 1, 2, 3, 4, 5, 6, 5, 8, 9], "v": range(10)})

    with pytest.raises(WriteV4ExecutionError) as error:
        _write(ms_engine, pdf, keys)

    message = str(error.value)
    assert f"MSSQL INSERT into '{keys}'" in message
    assert "partition rows 1-5" in message
    assert "does not report the failing row" in message
    assert "Violation of PRIMARY KEY" in message
    assert "rolled back" in message
    # Nothing of the failed partition is left. The other partition has its own transaction: it
    # stays committed only if dask ran it before the failure.
    assert _count(ms_engine, keys, "id >= 5") == 0
    assert _count(ms_engine, keys) in (0, 5)


@pytest.mark.parametrize(
    ("frame", "match"),
    [
        (pd.DataFrame({"id": [1, 2], "small": [1, 300], "note": ["a", "b"]}), "overflow"),
        (pd.DataFrame({"id": [1, 2], "small": [1, 2], "note": ["a", "abcdefg"]}), "truncated"),
    ],
)
def test_data_errors_are_not_retried(
    ms_engine: sa.Engine, fast_calls: list[str], frame: pd.DataFrame, match: str
) -> None:
    ranges = _name("ranges")
    _create(ms_engine, ranges, "id int, small tinyint, note nvarchar(5)")

    with pytest.raises(WriteV4ExecutionError, match=match):
        _write(ms_engine, frame, ranges, npartitions=1)

    assert fast_calls == []
    assert _count(ms_engine, ranges) == 0


def test_wide_mixed_50k_rows_match_the_source_and_the_inherited_path(
    ms_engine: sa.Engine, fast_calls: list[str]
) -> None:
    rows = 50_000
    wide_fast, wide_insert = _name("wide_fast"), _name("wide_insert")
    with ms_engine.begin() as conn:
        for name in (wide_fast, wide_insert):
            for statement in synthetic.create_table_sql("wide_mixed", "mssql", name):
                conn.exec_driver_sql(statement)
    pdf = pd.concat(
        [
            synthetic.generate_partition("wide_mixed", spec, SEED)
            for spec in synthetic.partition_plan(rows, 4)
        ],
        ignore_index=True,
    )

    assert (
        _write(ms_engine, pdf, wide_fast, npartitions=4, rows_per_batch=1_000, write_workers=4)
        == rows
    )
    assert len(fast_calls) == 4
    assert (
        _write(
            ms_engine,
            pdf,
            wide_insert,
            npartitions=4,
            mssql_fast_executemany=False,
            write_workers=4,
        )
        == rows
    )

    names = synthetic.column_names("wide_mixed")
    select = ", ".join(f"[{name}]" for name in names)
    with ms_engine.connect() as conn:
        got = [
            tuple(row)
            for row in conn.exec_driver_sql(f"SELECT {select} FROM [{wide_fast}] ORDER BY id")
        ]
        inserted = [
            tuple(row)
            for row in conn.exec_driver_sql(f"SELECT {select} FROM [{wide_insert}] ORDER BY id")
        ]
    assert got == inserted

    columns = dict(zip(names, zip(*got, strict=True), strict=True))

    def column(name: str) -> list:
        return pdf[name].to_numpy(dtype=object, na_value=None).tolist()

    for name in ("id", "int_a", "int_b", "float_a", "float_b", "str_low", "str_high", "str_text"):
        assert list(columns[name]) == column(name), name
    assert list(columns["str_null"]) == column("str_null")
    assert list(columns["bool_a"]) == pdf["bool_a"].tolist()
    # The server rounds the binary value of the float half away from zero.
    assert list(columns["amount"]) == [
        Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        for value in pdf["amount"].tolist()
    ]
    assert list(columns["ts_a"]) == pdf["ts_a"].dt.to_pydatetime().tolist()
    assert list(columns["date_a"]) == pdf["date_a"].dt.date.tolist()
    assert sum(value is None for value in columns["int_b"]) == int(pdf["int_b"].isna().sum()) > 0


def test_kill_switch_keeps_the_inherited_path(ms_engine: sa.Engine, fast_calls: list[str]) -> None:
    plain = _name("plain")
    _create(ms_engine, plain, "id int, name nvarchar(10)")

    assert type(resolve_executor(ms_engine, mssql_fast_executemany=False)) is SQLWriteExecutor
    written = _write(
        ms_engine,
        pd.DataFrame({"id": [1, 2], "name": _obj(["a", None])}),
        plain,
        mssql_fast_executemany=False,
    )

    assert written == 2
    assert fast_calls == []
    assert _rows_as_text(ms_engine, plain) == [("1", b"a\x00"), ("2", None)]
