from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Generator
from decimal import ROUND_HALF_UP, Decimal

import dask
import dask.dataframe as dd
import numpy as np
import pandas as pd
import pytest
import sqlalchemy as sa

from core.db.write_v4 import UpsertConfig, WriteMode, WriteRequest, WriteTarget, write_dataframe
from core.db.write_v4.errors import WriteV4ExecutionError
from core.db.write_v4.executors.pg import PostgresWriteExecutor
from core.db.write_v4.executors.sql import SQLWriteExecutor
from core.db.write_v4.resolver import resolve_executor

from services.task_benchmarking import synthetic

pytestmark = pytest.mark.docker_required

SEED = 42

# Every COPY-supported type with the edge values whose executemany semantics COPY must keep:
# NULL markers, rounding, float text, special characters, ns timestamps and time zones.
_PARITY_DDL = (
    "id int PRIMARY KEY, i2 smallint, i4 integer, i8 bigint, r real, f8 double precision, "
    "num numeric, num3 numeric(12,3), num_dec numeric(12,3), flag boolean, txt text, "
    "vc varchar(20), ch char(5), d date, d_aware date, ts timestamp, ts_aware timestamp, "
    "tstz timestamptz, tstz_naive timestamptz, u uuid, u_str uuid, ts_str timestamp"
)
_NS = pd.to_datetime(
    [
        "2020-01-01 00:00:00.0000017",
        "1969-12-31 23:59:59.9999995",
        None,
        "2024-02-29 23:30:00",
        "1999-12-31 23:59:59.995",
        "2020-06-01 12:00:00.0000025",
    ],
    format="ISO8601",
)


def _parity_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": range(6),
            "i2": pd.array([1, -32768, 32767, None, 0, 5], dtype="Int64"),
            "i4": [1.0, 2.5, -2.5, np.nan, 3.0, 1e9],
            "i8": np.array([0, 2**63 - 1, -(2**63), 5, 6, 7], dtype="int64"),
            "r": [0.1, 1 / 3, 3.4e38, np.nan, -0.0, 16777217.0],
            "f8": [0.1, 1 / 3, 1e300, 5e-324, float("inf"), np.nan],
            "num": [1.2345678901234567, 0.1 + 0.2, 76577.65, np.nan, 1e-20, 123456789012345678.0],
            "num3": [1.0005, -2.0015, 0.1 + 0.2, None, 1e-4, 76577.65],
            "num_dec": pd.Series(
                [
                    Decimal("1.5"),
                    Decimal("-0.0005"),
                    Decimal("123456789.1235"),
                    None,
                    Decimal("0"),
                    Decimal("1E+2"),
                ],
                dtype=object,
            ),
            "flag": pd.array([True, False, None, True, False, True], dtype="boolean"),
            "txt": pd.Series(
                ["", 'q"x,y', "line\nbreak\r\n", "\\N", None, "Привет \U0001f600 \\."],
                dtype=object,
            ),
            "vc": pd.Series(["a", " lead", "trail ", "NULL", None, "\t"], dtype=object),
            "ch": pd.Series(["ab", "", None, "abcde", "x", "y"], dtype=object),
            "d": _NS,
            "d_aware": _NS.tz_localize("UTC"),
            "ts": _NS,
            "ts_aware": _NS.tz_localize("Europe/Moscow"),
            "tstz": _NS.tz_localize("Europe/Moscow"),
            "tstz_naive": _NS,
            "u": pd.Series([uuid.UUID(int=i) for i in range(5)] + [None], dtype=object),
            "u_str": pd.Series(
                [
                    "{00000000-0000-0000-0000-000000000002}",
                    "A0EEBC999C0B4EF8BB6D6BB9BD380A11",
                    None,
                    "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12",
                    None,
                    "00000000-0000-0000-0000-000000000001",
                ],
                dtype=object,
            ),
            "ts_str": pd.Series(
                ["2020-01-01 10:00:00+05", "2020-01-01T10:00", None, "1999-12-31", "epoch", None],
                dtype=object,
            ),
        }
    )


@pytest.fixture(scope="module")
def pg_url(postgres_container) -> sa.URL:
    url = sa.make_url(postgres_container.get_connection_url())
    assert url.drivername == "postgresql+psycopg"
    return url


@pytest.fixture(scope="module")
def pg_engine(pg_url: sa.URL) -> Generator[sa.Engine]:
    engine = sa.create_engine(pg_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def schema(pg_engine: sa.Engine) -> Generator[str]:
    name = f"write_v4_pg_{uuid.uuid4().hex[:10]}"
    with pg_engine.begin() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA "{name}"'))
    try:
        yield name
    finally:
        with pg_engine.begin() as conn:
            conn.execute(sa.text(f'DROP SCHEMA "{name}" CASCADE'))


@pytest.fixture
def copy_calls(monkeypatch) -> list[str]:
    """Names of the tables whose partitions were written by a successful COPY."""
    calls: list[str] = []
    original = PostgresWriteExecutor._copy_partition

    def spy(self, table, *args, **kwargs):
        rows = original(self, table, *args, **kwargs)
        calls.append(table.name)
        return rows

    monkeypatch.setattr(PostgresWriteExecutor, "_copy_partition", spy)
    return calls


def _create(engine: sa.Engine, schema: str, table: str, ddl: str) -> None:
    with engine.begin() as conn:
        conn.execute(sa.text(f'CREATE TABLE "{schema}"."{table}" ({ddl})'))


def _write(
    engine: sa.Engine,
    pdf: pd.DataFrame,
    schema: str,
    table: str,
    *,
    npartitions: int = 2,
    **kwargs,
) -> int:
    request = WriteRequest(
        target=WriteTarget(table_name=table, schema_name=schema),
        **{"mode": WriteMode.APPEND, "write_workers": 1, **kwargs},
    )
    # Keep object columns (Decimal, UUID, raw strings) as built: dask would turn them into strings.
    with dask.config.set({"dataframe.convert-string": False}):
        ddf = dd.from_pandas(pdf, npartitions=npartitions, sort=False)
    return write_dataframe(ddf, engine, request).rows_written


def _rows_as_text(engine: sa.Engine, schema: str, table: str) -> list[tuple]:
    with engine.connect() as conn:
        names = [
            row[0]
            for row in conn.execute(
                sa.text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table ORDER BY ordinal_position"
                ),
                {"schema": schema, "table": table},
            )
        ]
        select = ", ".join(f'"{name}"::text' for name in names)
        return [
            tuple(row)
            for row in conn.execute(
                sa.text(f'SELECT {select} FROM "{schema}"."{table}" ORDER BY 1')
            )
        ]


def _count(engine: sa.Engine, schema: str, table: str, where: str = "true") -> int:
    with engine.connect() as conn:
        return conn.execute(
            sa.text(f'SELECT count(*) FROM "{schema}"."{table}" WHERE {where}')
        ).scalar_one()


@pytest.mark.parametrize("session_tz", ["UTC", "Asia/Kolkata"])
def test_copy_and_executemany_store_identical_values_for_every_supported_type(
    pg_url: sa.URL, schema: str, copy_calls: list[str], session_tz: str
) -> None:
    engine = sa.create_engine(pg_url, connect_args={"options": f"-c timezone={session_tz}"})
    try:
        assert isinstance(resolve_executor(engine), PostgresWriteExecutor)
        _create(engine, schema, "via_insert", _PARITY_DDL)
        _create(engine, schema, "via_copy", _PARITY_DDL)
        pdf = _parity_frame()

        assert _write(engine, pdf, schema, "via_insert", pg_copy=False) == len(pdf)
        assert copy_calls == []
        # rows_per_batch 1 still sends each partition as one COPY.
        assert _write(engine, pdf, schema, "via_copy", rows_per_batch=1) == len(pdf)
        assert copy_calls == ["via_copy", "via_copy"]

        expected = _rows_as_text(engine, schema, "via_insert")
        assert _rows_as_text(engine, schema, "via_copy") == expected
    finally:
        engine.dispose()
    # Spot checks of the shared semantics (columns in _PARITY_DDL order).
    row0, row1, row2, row4 = expected[0], expected[1], expected[2], expected[4]
    assert (row1[1], row1[2], row2[2]) == ("-32768", "2", "-2")  # float -> int: half to even
    assert row1[6] == "0.3"  # float -> numeric via %.15g
    assert row1[7] == "-2.002"  # numeric(12,3) rounds half away from zero
    assert row0[9] == "true"
    assert (row0[10], row4[10]) == ("", None)  # empty string stays empty, None is NULL
    if session_tz == "UTC":
        assert row0[15] == "2020-01-01 00:00:00.000001"  # ns floored to microseconds


def test_copy_handles_append_truncate_and_upsert(
    pg_engine: sa.Engine, schema: str, copy_calls: list[str]
) -> None:
    _create(pg_engine, schema, "events", "id int PRIMARY KEY, name text, amount numeric(10,2)")

    def frame(ids, names, amounts) -> pd.DataFrame:
        return pd.DataFrame({"id": ids, "name": names, "amount": amounts})

    assert (
        _write(
            pg_engine,
            frame([1, 2, 3, 4], ["a", "b", None, "d"], [1.005, 2.5, 3.0, None]),
            schema,
            "events",
        )
        == 4
    )
    assert copy_calls == ["events", "events"]

    upsert = frame([3, 5], ["c2", "e"], [30.0, 50.125])
    assert (
        _write(
            pg_engine,
            upsert,
            schema,
            "events",
            mode=WriteMode.UPSERT,
            upsert=UpsertConfig(key_column="id"),
        )
        == 2
    )
    # Upsert stages through a scratch table: COPY writes into it.
    assert len(copy_calls) == 4
    assert all(name.startswith("events") for name in copy_calls[2:])
    assert copy_calls[2] != "events"
    assert _rows_as_text(pg_engine, schema, "events") == [
        ("1", "a", "1.01"),
        ("2", "b", "2.50"),
        ("3", "c2", "30.00"),
        ("4", "d", None),
        ("5", "e", "50.13"),
    ]

    assert (
        _write(
            pg_engine,
            frame([10], ["z"], [0.5]),
            schema,
            "events",
            mode=WriteMode.TRUNCATE,
            npartitions=1,
        )
        == 1
    )
    assert len(copy_calls) == 5
    assert _rows_as_text(pg_engine, schema, "events") == [("10", "z", "0.50")]


def test_unsupported_column_types_write_the_whole_table_through_executemany(
    pg_engine: sa.Engine, schema: str, copy_calls: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    _create(pg_engine, schema, "docs", "id int PRIMARY KEY, payload jsonb, tags int[], note text")
    pdf = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "payload": pd.Series([{"a": 1}, {"b": [1, 2]}, None], dtype=object),
            "tags": pd.Series([[1, 2], [], None], dtype=object),
            "note": ["x", "", None],
        }
    )

    with caplog.at_level(logging.WARNING, logger="core.db.write_v4.executors.pg"):
        assert _write(pg_engine, pdf, schema, "docs") == 3

    assert copy_calls == []
    warnings = [
        record.getMessage()
        for record in caplog.records
        if "COPY is not used" in record.getMessage()
    ]
    assert len(warnings) == 1
    assert "payload (jsonb)" in warnings[0]
    assert "tags (_int4)" in warnings[0]
    assert _rows_as_text(pg_engine, schema, "docs") == [
        ("1", '{"a": 1}', "{1,2}", "x"),
        ("2", '{"b": [1, 2]}', "{}", ""),
        # executemany behavior kept as is: SQLAlchemy JSONB binds None as JSON 'null'.
        ("3", "null", None, None),
    ]


def test_constraint_violation_rolls_back_only_its_partition_and_names_the_row(
    pg_engine: sa.Engine, schema: str
) -> None:
    _create(pg_engine, schema, "keys", "id int PRIMARY KEY, v int")
    # Partition 1: ids 0..4. Partition 2: ids 5, 6, 5, 8, 9 -> duplicate key at its row 3.
    pdf = pd.DataFrame({"id": [0, 1, 2, 3, 4, 5, 6, 5, 8, 9], "v": range(10)})

    with pytest.raises(WriteV4ExecutionError) as error:
        _write(pg_engine, pdf, schema, "keys")

    message = str(error.value)
    assert "PostgreSQL COPY into" in message and "keys" in message
    assert "at row 3 of the partition" in message
    assert "duplicate key value violates unique constraint" in message
    assert "rolled back" in message
    # Nothing of the failed partition is left. The other partition has its own transaction: it
    # stays committed only if dask ran it before the failure (the sync scheduler runs it after).
    assert _count(pg_engine, schema, "keys", "id >= 5") == 0
    assert _count(pg_engine, schema, "keys") in (0, 5)


def test_data_errors_are_not_retried_and_name_row_and_column(
    pg_engine: sa.Engine, schema: str, copy_calls: list[str]
) -> None:
    _create(pg_engine, schema, "ranges", "id int, small int, note text")

    with pytest.raises(
        WriteV4ExecutionError, match=r"at row 2 of the partition, column 'small'.*out of range"
    ):
        _write(
            pg_engine,
            pd.DataFrame({"id": [1, 2], "small": [1, 2**31], "note": ["a", "b"]}),
            schema,
            "ranges",
            npartitions=1,
        )

    with pytest.raises(
        WriteV4ExecutionError, match=r"Column 'note' .* NUL \(0x00\) character at row 2"
    ):
        _write(
            pg_engine,
            pd.DataFrame(
                {"id": [1, 2], "small": [1, 2], "note": pd.Series(["a", "b\x00c"], dtype=object)}
            ),
            schema,
            "ranges",
            npartitions=1,
        )

    assert copy_calls == []
    assert _count(pg_engine, schema, "ranges") == 0


def test_wide_mixed_50k_rows_match_the_source_and_executemany(
    pg_engine: sa.Engine, schema: str, copy_calls: list[str]
) -> None:
    rows = 50_000
    for name in ("wide_copy", "wide_insert"):
        with pg_engine.begin() as conn:
            for statement in synthetic.create_table_sql("wide_mixed", "postgres", name, schema):
                conn.execute(sa.text(statement))
    pdf = pd.concat(
        [
            synthetic.generate_partition("wide_mixed", spec, SEED)
            for spec in synthetic.partition_plan(rows, 4)
        ],
        ignore_index=True,
    )

    # Bulk workers above write_workers: the COPY partitions run in 4 threads.
    written = _write(
        pg_engine,
        pdf,
        schema,
        "wide_copy",
        npartitions=4,
        rows_per_batch=3_000,
        write_workers=1,
        bulk_write_workers=4,
    )
    assert written == rows
    assert len(copy_calls) == 4
    assert (
        _write(pg_engine, pdf, schema, "wide_insert", npartitions=4, pg_copy=False, write_workers=2)
        == rows
    )

    names = synthetic.column_names("wide_mixed")
    with pg_engine.connect() as conn:
        got = dict(
            zip(
                names,
                zip(
                    *conn.execute(sa.text(f'SELECT * FROM "{schema}"."wide_copy" ORDER BY id')),
                    strict=True,
                ),
                strict=True,
            )
        )
        differences = [
            conn.execute(
                sa.text(
                    f'SELECT count(*) FROM (TABLE "{schema}"."{a}" EXCEPT ALL TABLE "{schema}"."{b}") d'
                )
            ).scalar_one()
            for a, b in (("wide_copy", "wide_insert"), ("wide_insert", "wide_copy"))
        ]
        totals = conn.execute(
            sa.text(
                "SELECT count(*), sum(id), sum(int_b), count(*) FILTER (WHERE int_b IS NULL), "
                "count(*) FILTER (WHERE str_null IS NULL), sum(amount), "
                "md5(string_agg(str_text, '|' ORDER BY id)) "
                f'FROM "{schema}"."wide_copy"'
            )
        ).one()
    assert differences == [0, 0]

    def column(name: str) -> list:
        return pdf[name].to_numpy(dtype=object, na_value=None).tolist()

    for name in (
        "id",
        "int_a",
        "int_b",
        "float_a",
        "float_b",
        "bool_a",
        "str_low",
        "str_high",
        "str_text",
        "str_null",
    ):
        assert list(got[name]) == column(name), name
    expected_amount = [
        Decimal(format(value, ".15g")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        for value in pdf["amount"].tolist()
    ]
    assert list(got["amount"]) == expected_amount
    assert list(got["ts_a"]) == pdf["ts_a"].dt.floor("us").dt.to_pydatetime().tolist()
    assert list(got["date_a"]) == pdf["date_a"].dt.date.tolist()
    assert tuple(totals) == (
        rows,
        int(pdf["id"].sum()),
        int(pdf["int_b"].sum()),
        int(pdf["int_b"].isna().sum()),
        int(pdf["str_null"].isna().sum()),
        sum(expected_amount, Decimal(0)),
        hashlib.md5("|".join(pdf["str_text"].tolist()).encode()).hexdigest(),
    )
    assert totals[3] > 0 and totals[4] > 0


def test_kill_switch_keeps_executemany(
    pg_engine: sa.Engine, schema: str, copy_calls: list[str]
) -> None:
    _create(pg_engine, schema, "plain", "id int, name text")

    assert type(resolve_executor(pg_engine, pg_copy=False)) is SQLWriteExecutor
    assert (
        _write(
            pg_engine,
            pd.DataFrame({"id": [1, 2], "name": ["a", None]}),
            schema,
            "plain",
            pg_copy=False,
        )
        == 2
    )

    assert copy_calls == []
    assert _rows_as_text(pg_engine, schema, "plain") == [("1", "a"), ("2", None)]
