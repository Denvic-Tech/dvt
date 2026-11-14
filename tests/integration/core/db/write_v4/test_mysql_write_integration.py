from __future__ import annotations

import logging
import uuid
from collections.abc import Generator
from datetime import date, time, timedelta
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
from core.db.write_v4.executors.mysql import MysqlWriteExecutor
from core.db.write_v4.executors.sql import SQLWriteExecutor
from core.db.write_v4.resolver import resolve_executor

from services.task_benchmarking import synthetic

pytestmark = pytest.mark.docker_required

SEED = 42

# Every allow-listed type with the edge values whose PyMySQL literals the bulk path must keep:
# NULL markers, float and Decimal text, nanosecond timestamps, aware datetimes, quotes,
# backslashes and percent signs, non-BMP text, NUL bytes, bytes-like objects.
_PARITY_DDL = (
    "id bigint PRIMARY KEY, ti tinyint, b1 tinyint(1), bo boolean, si smallint, mi mediumint, "
    "i int, i_float int, i_str int, bi bigint, ubi bigint unsigned, f float, d double, "
    "de decimal(18,2), de_f decimal(18,2), bt bit(8), c char(5), vc varchar(20), "
    "vc_arrow varchar(64), t text, mt mediumtext, dt date, dt_obj date, dtt datetime, "
    "dtt3 datetime(3), dtt6 datetime(6), dtt_aware datetime(6), dtt_ms datetime(6), "
    "ts timestamp(6) NULL, tm time(3), tm_td time(6), y year, bn binary(4), vb varbinary(10), "
    "bl blob"
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
_TS = pd.to_datetime(
    [
        "2020-01-01 00:00:00.0000017",
        "1999-12-31 23:59:59.9999995",
        None,
        "2024-02-29 23:30:00",
        "2030-12-31 23:59:59.9995",
        "2020-06-01 12:00:00.123",
    ],
    format="ISO8601",
).astype("datetime64[ns]")


def _obj(values) -> pd.Series:
    return pd.Series(values, dtype=object)


def _parity_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": range(6),
            "ti": pd.array([0, 127, None, -128, 2, 3], dtype="Int64"),
            "b1": np.array([True, False, True, False, True, False]),
            "bo": pd.array([True, False, None, True, False, True], dtype="boolean"),
            "si": np.array([-32768, 32767, 0, 1, 2, 3], dtype="int16"),
            "mi": np.array([-8388608, 8388607, 0, 1, 2, 3], dtype="int32"),
            "i": np.array([2**31 - 1, -(2**31), 0, 1, 2, 3], dtype="int32"),
            "i_float": [1.0, 2.7, -2.5, np.nan, 3.5, 1e9],
            "i_str": _obj(["42", " 7 ", None, "-1", "0", "3"]),
            "bi": np.array([0, 2**63 - 1, -(2**63), 5, 6, 7], dtype="int64"),
            "ubi": np.array([0, 2**64 - 1, 2**63, 5, 6, 7], dtype="uint64"),
            "f": np.array([0.1, 1 / 3, 3.4e38, np.nan, -0.0, 16777217.0], dtype="float32"),
            "d": [0.1, 1 / 3, 1e300, 2.2250738585072014e-308, -0.0, np.nan],
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
            "de_f": [1.005, 2.675, 0.1 + 0.2, np.nan, 1e-4, 76577.65],
            "bt": pd.array([0, 255, None, 1, 128, 7], dtype="Int64"),
            "c": _obj(["ab", "", None, "abcde", "x", "é"]),
            "vc": _obj(["a", " lead", "trail ", None, "é" * 15, "Привет \U0001f600"]),
            "vc_arrow": pd.array(
                ["a", None, "б", "", "\U0001f600", "q'\"\\%s"],
                dtype=pd.ArrowDtype(pa.large_string()),
            ),
            "t": pd.array(["x" * 9000, "", None, "y", "%s %%", "\\N"], dtype="string"),
            "mt": _obj(["ж" * 5000, None, "\U0001f600" * 3000, "", "a\x00b", "b"]),
            "dt": _NS,
            "dt_obj": _obj(
                [
                    date(2020, 1, 2),
                    None,
                    date(1000, 1, 1),
                    date(9999, 12, 31),
                    date(2024, 2, 29),
                    date(1970, 1, 1),
                ]
            ),
            "dtt": _NS,
            "dtt3": _NS,
            "dtt6": _NS,
            "dtt_aware": _NS.tz_localize("Europe/Moscow"),
            "dtt_ms": _NS.astype("datetime64[ms]"),
            "ts": _TS,
            "tm": _obj(
                [
                    time(1, 2, 3, 4567),
                    None,
                    time(23, 59, 59, 999999),
                    time(0, 0),
                    time(12, 0, 0, 500),
                    time(1),
                ]
            ),
            "tm_td": _obj(
                [
                    timedelta(days=1, hours=2, microseconds=5),
                    None,
                    timedelta(seconds=-1),
                    timedelta(0),
                    timedelta(hours=838, minutes=59, seconds=59),
                    None,
                ]
            ),
            "y": pd.array([1901, 2155, None, 2000, 1999, 2024], dtype="Int64"),
            "bn": _obj([b"ab", b"\x00\x01\x02\x03", None, b"", bytearray(b"z"), b"abcd"]),
            "vb": _obj([b"\x00", b"'\\", None, b"", memoryview(b"mv"), b"0123456789"]),
            "bl": _obj([b"x" * 60000, None, b"", b"\xff", b"%s", b"\\N"]),
        }
    )


@pytest.fixture(scope="module")
def my_url(mysql_container) -> sa.URL:
    url = sa.make_url(mysql_container.get_connection_url())
    assert url.drivername == "mysql+pymysql"
    return url


@pytest.fixture(scope="module")
def my_engine(my_url: sa.URL) -> Generator[sa.Engine]:
    engine = sa.create_engine(my_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def bulk_calls(monkeypatch) -> list[str]:
    """Names of the tables whose partitions were written by a successful bulk insert."""
    calls: list[str] = []
    original = MysqlWriteExecutor._bulk_insert

    def spy(self, table, *args, **kwargs):
        rows = original(self, table, *args, **kwargs)
        calls.append(table.name)
        return rows

    monkeypatch.setattr(MysqlWriteExecutor, "_bulk_insert", spy)
    return calls


def _name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _create(engine: sa.Engine, table: str, ddl: str) -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql(f"CREATE TABLE `{table}` ({ddl})")


def _write(
    engine: sa.Engine, pdf: pd.DataFrame, table: str, *, npartitions: int = 2, **kwargs
) -> int:
    request = WriteRequest(
        target=WriteTarget(table_name=table),
        **{"mode": WriteMode.APPEND, "write_workers": 1, **kwargs},
    )
    # Keep object columns (Decimal, bytes, raw strings) as built: dask would turn them into strings.
    with dask.config.set({"dataframe.convert-string": False}):
        ddf = dd.from_pandas(pdf, npartitions=npartitions, sort=False)
    return write_dataframe(ddf, engine, request).rows_written


def _rows_as_text(engine: sa.Engine, table: str) -> list[tuple]:
    """Rows as exact text: HEX of strings, bytes and bits (no collation folding)."""
    with engine.connect() as conn:
        columns = conn.exec_driver_sql(
            "SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
            (table,),
        ).all()
        expressions = [
            f"HEX(`{name}`)"
            if data_type
            in ("char", "varchar", "text", "mediumtext", "binary", "varbinary", "blob", "bit")
            else f"CAST(`{name}` AS CHAR)"
            for name, data_type in columns
        ]
        statement = f"SELECT {', '.join(expressions)} FROM `{table}` ORDER BY `{columns[0][0]}`"
        return [tuple(row) for row in conn.exec_driver_sql(statement)]


def _count(engine: sa.Engine, table: str, where: str = "TRUE") -> int:
    with engine.connect() as conn:
        return conn.exec_driver_sql(f"SELECT count(*) FROM `{table}` WHERE {where}").scalar_one()


def test_bulk_and_inherited_path_store_identical_values_for_every_type(
    my_engine: sa.Engine, bulk_calls: list[str]
) -> None:
    assert isinstance(resolve_executor(my_engine), MysqlWriteExecutor)
    via_insert, via_bulk = _name("via_insert"), _name("via_bulk")
    _create(my_engine, via_insert, _PARITY_DDL)
    _create(my_engine, via_bulk, _PARITY_DDL)
    pdf = _parity_frame()

    assert _write(my_engine, pdf, via_insert, mysql_bulk_insert=False) == len(pdf)
    assert bulk_calls == []
    assert _write(my_engine, pdf, via_bulk, rows_per_batch=1) == len(pdf)
    assert bulk_calls == [via_bulk, via_bulk]

    expected = _rows_as_text(my_engine, via_insert)
    assert _rows_as_text(my_engine, via_bulk) == expected
    # Spot checks of the shared semantics (columns in _PARITY_DDL order).
    row0, row1, row5 = expected[0], expected[1], expected[5]
    assert row1[14] == "2.68"  # float -> decimal: repr text is an exact literal, half up
    assert row0[25] == "2020-01-01 00:00:00.000002"  # nanosecond text rounded by the server
    assert row0[16] == "6162"  # 'ab'
    assert row5[18] == "7127225C2573"  # q'"\%s
    assert row0[20] == "D0B6" * 5000


def test_bulk_insert_handles_append_truncate_and_upsert(
    my_engine: sa.Engine, bulk_calls: list[str]
) -> None:
    events = _name("events")
    _create(my_engine, events, "id int PRIMARY KEY, name varchar(20), amount decimal(10,2)")

    def frame(ids, names, amounts) -> pd.DataFrame:
        return pd.DataFrame({"id": ids, "name": names, "amount": amounts})

    first = frame([1, 2, 3, 4], ["a", "b", None, "d"], [1.005, 2.5, 3.0, None])
    assert _write(my_engine, first, events) == 4
    assert bulk_calls == [events, events]

    upsert = frame([3, 5], ["c2", "e"], [30.0, 50.125])
    written = _write(
        my_engine, upsert, events, mode=WriteMode.UPSERT, upsert=UpsertConfig(key_column="id")
    )
    assert written == 2
    # Upsert stages through a scratch table: the bulk path writes into it.
    assert len(bulk_calls) == 4
    assert all(name.startswith(events) and name != events for name in bulk_calls[2:])
    assert _rows_as_text(my_engine, events) == [
        ("1", "61", "1.01"),
        ("2", "62", "2.50"),
        ("3", "6332", "30.00"),
        ("4", "64", None),
        ("5", "65", "50.13"),
    ]

    replacement = frame([10], ["z"], [0.5])
    assert _write(my_engine, replacement, events, mode=WriteMode.TRUNCATE, npartitions=1) == 1
    assert len(bulk_calls) == 5
    assert _rows_as_text(my_engine, events) == [("10", "7A", "0.50")]


def test_unsupported_column_types_write_the_whole_table_through_the_inherited_path(
    my_engine: sa.Engine, bulk_calls: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    docs = _name("docs")
    _create(my_engine, docs, "id int PRIMARY KEY, payload json, kind enum('a','b'), note text")
    pdf = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "payload": _obj([{"a": 1}, [1, 2], None]),
            "kind": _obj(["a", "b", None]),
            "note": _obj(["x", "", None]),
        }
    )

    with caplog.at_level(logging.WARNING, logger="core.db.write_v4.executors.mysql"):
        assert _write(my_engine, pdf, docs) == 3

    assert bulk_calls == []
    warnings = [r.getMessage() for r in caplog.records if "is not used" in r.getMessage()]
    assert len(warnings) == 1
    assert "payload (json)" in warnings[0] and "kind (enum)" in warnings[0]
    assert _rows_as_text(my_engine, docs) == [
        ("1", '{"a": 1}', "a", "78"),
        ("2", "[1, 2]", "b", ""),
        # Inherited behavior kept as is: SQLAlchemy JSON binds None as JSON 'null'.
        ("3", "null", None, None),
    ]


def test_constraint_violation_rolls_back_only_its_partition(my_engine: sa.Engine) -> None:
    # Two rows per executemany call: the failing call follows a successful one.
    keys = _name("keys")
    _create(my_engine, keys, "id int PRIMARY KEY, v int")
    # Partition 1: ids 0..4. Partition 2: ids 5, 6, 5, 8, 9 -> duplicate key at its row 3.
    pdf = pd.DataFrame({"id": [0, 1, 2, 3, 4, 5, 6, 5, 8, 9], "v": range(10)})

    with pytest.raises(WriteV4ExecutionError) as error:
        _write(my_engine, pdf, keys, rows_per_batch=2)

    message = str(error.value)
    assert f"MySQL INSERT into '{keys}' failed: (1062) Duplicate entry '5'" in message
    assert "rolled back" in message
    # Rows 5, 6 were inserted by an earlier call of the same transaction and are rolled back.
    assert _count(my_engine, keys, "id >= 5") == 0
    assert _count(my_engine, keys) in (0, 5)


@pytest.mark.parametrize(
    ("frame", "match"),
    [
        (pd.DataFrame({"id": [1, 2], "small": [1, 300], "note": ["a", "b"]}), r"\(1264\)"),
        (pd.DataFrame({"id": [1, 2], "small": [1, 2], "note": ["a", "abcdefg"]}), r"\(1406\)"),
        (pd.DataFrame({"id": [1, 2], "small": [1.0, float("inf")], "note": ["a", "b"]}), "inf"),
    ],
)
def test_data_errors_are_not_retried(
    my_engine: sa.Engine, bulk_calls: list[str], frame: pd.DataFrame, match: str
) -> None:
    ranges = _name("ranges")
    _create(my_engine, ranges, "id int, small tinyint, note varchar(5)")

    with pytest.raises(WriteV4ExecutionError, match=match):
        _write(my_engine, frame, ranges, npartitions=1)

    assert bulk_calls == []
    assert _count(my_engine, ranges) == 0


def _wide_mixed(rows: int, npartitions: int) -> pd.DataFrame:
    return pd.concat(
        [
            synthetic.generate_partition("wide_mixed", spec, SEED)
            for spec in synthetic.partition_plan(rows, npartitions)
        ],
        ignore_index=True,
    )


def _create_wide(engine: sa.Engine, name: str) -> None:
    with engine.begin() as conn:
        for statement in synthetic.create_table_sql("wide_mixed", "mysql", name):
            conn.exec_driver_sql(statement)


def _select_wide(engine: sa.Engine, name: str) -> list[tuple]:
    names = synthetic.column_names("wide_mixed")
    select = ", ".join(f"`{column}`" for column in names)
    with engine.connect() as conn:
        return [
            tuple(row) for row in conn.exec_driver_sql(f"SELECT {select} FROM `{name}` ORDER BY id")
        ]


def test_wide_mixed_50k_rows_match_the_source_and_the_inherited_path(
    my_engine: sa.Engine, bulk_calls: list[str]
) -> None:
    rows = 50_000
    wide_bulk, wide_insert = _name("wide_bulk"), _name("wide_insert")
    _create_wide(my_engine, wide_bulk)
    _create_wide(my_engine, wide_insert)
    pdf = _wide_mixed(rows, 4)

    assert (
        _write(my_engine, pdf, wide_bulk, npartitions=4, rows_per_batch=5_000, write_workers=4)
        == rows
    )
    assert len(bulk_calls) == 4
    assert (
        _write(my_engine, pdf, wide_insert, npartitions=4, mysql_bulk_insert=False, write_workers=4)
        == rows
    )

    got = _select_wide(my_engine, wide_bulk)
    assert got == _select_wide(my_engine, wide_insert)
    names = synthetic.column_names("wide_mixed")
    columns = dict(zip(names, zip(*got, strict=True), strict=True))

    def column(name: str) -> list:
        return pdf[name].to_numpy(dtype=object, na_value=None).tolist()

    for name in ("id", "int_a", "int_b", "float_a", "float_b", "str_low", "str_high", "str_text"):
        assert list(columns[name]) == column(name), name
    assert list(columns["str_null"]) == column("str_null")
    assert list(columns["bool_a"]) == [int(value) for value in pdf["bool_a"].tolist()]
    # PyMySQL sends repr(float), an exact DECIMAL literal that the server rounds half up.
    assert list(columns["amount"]) == [
        Decimal(repr(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        for value in pdf["amount"].tolist()
    ]
    assert list(columns["ts_a"]) == pdf["ts_a"].dt.to_pydatetime().tolist()
    assert list(columns["date_a"]) == pdf["date_a"].dt.date.tolist()
    assert sum(value is None for value in columns["int_b"]) == int(pdf["int_b"].isna().sum()) > 0


def test_statements_stay_below_a_small_max_allowed_packet(
    mysql_container, my_url: sa.URL, bulk_calls: list[str]
) -> None:
    root = sa.create_engine(
        my_url.set(username="root", password=mysql_container.root_password),
        isolation_level="AUTOCOMMIT",
    )
    with root.connect() as conn:
        previous = conn.exec_driver_sql("SELECT @@global.max_allowed_packet").scalar_one()
        conn.exec_driver_sql("SET GLOBAL max_allowed_packet = 1048576")
    engine = sa.create_engine(my_url)  # new sessions take the lowered global value
    try:
        wide = _name("wide_packet")
        _create_wide(engine, wide)
        pdf = _wide_mixed(20_000, 1)

        # 20 000 rows of about 250 bytes per executemany: PyMySQL splits them into statements
        # below the 1 MiB packet instead of failing with "packet bigger than max_allowed_packet".
        assert _write(engine, pdf, wide, npartitions=1, rows_per_batch=20_000) == 20_000
        assert bulk_calls == [wide]
        assert [row[0] for row in _select_wide(engine, wide)] == pdf["id"].tolist()
    finally:
        engine.dispose()
        with root.connect() as conn:
            conn.exec_driver_sql(f"SET GLOBAL max_allowed_packet = {int(previous)}")
        root.dispose()


def test_kill_switch_keeps_the_inherited_path(my_engine: sa.Engine, bulk_calls: list[str]) -> None:
    plain = _name("plain")
    _create(my_engine, plain, "id int, name varchar(10)")

    assert type(resolve_executor(my_engine, mysql_bulk_insert=False)) is SQLWriteExecutor
    written = _write(
        my_engine,
        pd.DataFrame({"id": [1, 2], "name": _obj(["a", None])}),
        plain,
        mysql_bulk_insert=False,
    )

    assert written == 2
    assert bulk_calls == []
    assert _rows_as_text(my_engine, plain) == [("1", "61"), ("2", None)]
