"""PostgreSQL read_v3 executor: an ADBC Arrow fetch path for segment queries.

A segment is fetched through ``adbc_driver_postgresql`` (binary ``COPY ... TO STDOUT``) and
converted column by column into exactly the dtypes and values the current path produces
(``sql_runner.query_df`` over psycopg 3 text results, then ``_apply_output_type_hints``).
Eligibility is decided once per plan from the described result schema: every needed column must
be an allow-listed combination of PostgreSQL type, Arrow type and target dtype (see
``_converter_for``); anything else reads the plan through ``query_df``. A segment whose ADBC
fetch or conversion fails is re-read through ``query_df``; a connection-level failure switches
the Arrow path off for the executor's life. Planning and ``build_meta`` keep the SQL runner.

ADBC is optional: without ``adbc_driver_postgresql`` the resolver keeps ``SQLReadExecutor``.
"""

from __future__ import annotations

import json
import logging
import threading
import weakref
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from functools import partial
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
from sqlalchemy.engine import Engine

from core.db.read_v3.dialects.base import SQLDialect
from core.db.read_v3.errors import ReadV3ExecutionError
from core.db.read_v3.executors.sql import SQLReadExecutor
from core.db.read_v3.models import PartitionStrategy, ReadV3Plan
from core.db.read_v3.sql_runner import execute_literal_sql

try:
    import adbc_driver_postgresql.dbapi as _adbc_dbapi
    from adbc_driver_manager import Error as _AdbcError
except ImportError:  # pragma: no cover - exercised through adbc_available() in tests
    _adbc_dbapi = None

    class _AdbcError(Exception):  # type: ignore[no-redef]
        """Placeholder so except clauses stay valid without ADBC."""


logger = logging.getLogger(__name__)

_DEFAULT_CONNECTION_POOL_SIZE = 4
# Idle pooled ADBC connections close this long after the last running segment query of the
# executor finished, so no server session outlives the read by more than about this delay.
_IDLE_CLOSE_DELAY_SEC = 1.0
# Plans with fewer rows read through query_df: opening the ADBC connections (the driver loads
# the type catalog on connect) costs more than the Arrow fetch saves on small reads. Equal to
# the planner's default rows-per-partition step, so single-default-partition reads stay there.
_MIN_ARROW_ROWS = 100_000

_ARROW_ERRORS = (pa.ArrowInvalid, pa.ArrowNotImplementedError, pa.ArrowTypeError)

_PG_INT_TYPES: dict[str, pa.DataType] = {
    "int2": pa.int16(),
    "int4": pa.int32(),
    "int8": pa.int64(),
}
_PG_TEXT_TYPES = frozenset({"text", "varchar", "bpchar", "name"})
_PG_BUILTIN_TYPES = frozenset(
    {
        *_PG_INT_TYPES,
        *_PG_TEXT_TYPES,
        "numeric",
        "float4",
        "float8",
        "bool",
        "date",
        "timestamp",
        "timestamptz",
        "uuid",
        "json",
        "jsonb",
    }
)
_NAIVE_DATETIME_DTYPES = frozenset(
    {"datetime64[s]", "datetime64[ms]", "datetime64[us]", "datetime64[ns]"}
)
_INT64_DTYPE_MAPPER = {pa.int64(): pd.Int64Dtype()}.get
_BOOLEAN_DTYPE_MAPPER = {pa.bool_(): pd.BooleanDtype()}.get

# psycopg 3 raises for dates and timestamps outside Python's datetime range (BC, year > 9999,
# +/-infinity); such values send the segment through query_df so it ends in today's error.
_MIN_DATE_DAYS = (date(1, 1, 1) - date(1970, 1, 1)).days
_MAX_DATE_DAYS = (date(9999, 12, 31) - date(1970, 1, 1)).days
_DAY_US = 86_400 * 1_000_000
_MIN_TIMESTAMP_US = _MIN_DATE_DAYS * _DAY_US  # 0001-01-01 00:00:00
_MAX_TIMESTAMP_US = (_MAX_DATE_DAYS + 1) * _DAY_US - 1  # 9999-12-31 23:59:59.999999
# timestamptz is converted by psycopg into the session time zone; one day of margin keeps every
# zone offset inside Python's range.
_MIN_TIMESTAMPTZ_US = _MIN_TIMESTAMP_US + _DAY_US
_MAX_TIMESTAMPTZ_US = _MAX_TIMESTAMP_US - _DAY_US

# PostgreSQL 12+ prints floats in the shortest round-trip form while extra_float_digits > 0
# (psycopg parses that text). float4 additionally excludes the rounding-interval bounds:
# 15125440512 prints as 1.5125441e+10, while Arrow's (and numpy's) shortest text 1.512544e+10
# lies on the bound; _float4_to_float64 reproduces PostgreSQL's choice.
_FLOAT8_PROBE = "0.30000000000000004"
_FLOAT4_PROBE = "1.5125441e+10"
_SESSION_SQL = (
    "SELECT current_user::text AS current_user_name, session_user::text AS session_user_name, "
    "current_database()::text AS database_name, "
    "pg_postmaster_start_time()::text AS server_started, "
    "coalesce(inet_server_port(), 0) AS server_port, "
    "current_setting('server_version_num') AS server_version_num, "
    "current_setting('server_encoding') AS server_encoding, "
    "current_setting('client_encoding') AS client_encoding, "
    "current_setting('DateStyle') AS date_style, "
    "current_setting('TimeZone') AS time_zone, "
    "current_setting('search_path') AS search_path, "
    "coalesce((SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()), false) AS ssl, "
    "coalesce((SELECT encrypted FROM pg_stat_gssapi WHERE pid = pg_backend_pid()), false) "
    "AS gss_encrypted, "
    "coalesce((SELECT string_agg(name || '=' || setting, ';' ORDER BY name) FROM pg_settings "
    "WHERE source IN ('client', 'session') AND name <> 'application_name'), '') "
    "AS session_settings, "
    "(0.1::float8 + 0.2::float8)::text AS float8_text, "
    "'15125440512'::float4::text AS float4_text"
)
_ENUM_SQL = "SELECT bool_and(typtype = 'e') AS is_enum FROM pg_type WHERE typname = $1"
# libpq options psycopg itself fills in (it resolves host names into hostaddr, which can differ
# between two connections to the same host name).
_IGNORED_LIVE_OPTIONS = frozenset({"hostaddr"})

_ADBC_MISSING_LOGGED = threading.Event()


def adbc_available() -> bool:
    """Whether the ADBC PostgreSQL driver can be imported; logs its absence once at debug level."""
    if _adbc_dbapi is not None:
        return True
    if not _ADBC_MISSING_LOGGED.is_set():
        _ADBC_MISSING_LOGGED.set()
        logger.debug("adbc_driver_postgresql is not installed; read_v3 PostgreSQL uses query_df")
    return False


class _ConversionError(ValueError):
    """The Arrow result cannot be converted into the current path's dtypes and values."""


class _ConnectionFailure(Exception):
    """An ADBC connection could not be opened or does not match the SQLAlchemy session."""


@dataclass(frozen=True)
class _SessionInfo:
    conninfo: str = field(repr=False)
    fingerprint: Mapping[str, str]
    float4_text_ok: bool
    float8_text_ok: bool


@dataclass(frozen=True)
class _ArrowPlan:
    # (name, Arrow type, PostgreSQL type) of every result column; a fetched table must match.
    signature: tuple[tuple[str, str, str], ...]
    # Result column -> (converter, target dtype); other columns are helpers load_partition drops.
    converters: Mapping[str, tuple[str, str]]


def _pg_type_name(arrow_field: pa.Field) -> str:
    return (arrow_field.metadata or {}).get(b"POSTGRESQL:type", b"").decode("utf-8", "replace")


def _unwrap_type(arrow_field: pa.Field) -> tuple[str | None, pa.DataType]:
    arrow_type = arrow_field.type
    if isinstance(arrow_type, pa.BaseExtensionType):
        return arrow_type.extension_name, arrow_type.storage_type
    extension = (arrow_field.metadata or {}).get(b"ARROW:extension:name")
    return (extension.decode("utf-8", "replace") if extension else None), arrow_type


def _schema_signature(schema: pa.Schema) -> tuple[tuple[str, str, str], ...]:
    return tuple((f.name, str(f.type), _pg_type_name(f)) for f in schema)


def _storage(chunked: pa.ChunkedArray) -> pa.ChunkedArray:
    if isinstance(chunked.type, pa.BaseExtensionType):
        return pa.chunked_array(
            [chunk.storage for chunk in chunked.chunks], type=chunked.type.storage_type
        )
    return chunked


def _converter_for(  # noqa: PLR0911
    arrow_field: pa.Field,
    target: str,
    *,
    index_helper: bool,
    enum_types: frozenset[str],
    session: _SessionInfo,
    json_ok: bool,
) -> str | None:
    """Converter name for an allow-listed (PostgreSQL type, Arrow type, target dtype), else None."""
    pg_type = _pg_type_name(arrow_field)
    extension, arrow_type = _unwrap_type(arrow_field)
    int_type = _PG_INT_TYPES.get(pg_type)
    if index_helper:
        # Raw helper index (key alias, hash bucket, grouping literal): query_df infers int64.
        return "int_index" if int_type is not None and arrow_type == int_type else None
    if int_type is not None:
        return "int" if arrow_type == int_type and target == "Int64" else None
    if pg_type == "numeric":
        if not pa.types.is_string(arrow_type):
            return None
        return {"Int64": "numeric_int", "float64": "numeric_float"}.get(target)
    if pg_type == "float4":
        ok = arrow_type == pa.float32() and target == "float64" and session.float4_text_ok
        return "float4" if ok else None
    if pg_type == "float8":
        ok = arrow_type == pa.float64() and target == "float64" and session.float8_text_ok
        return "float8" if ok else None
    if pg_type == "bool":
        return "bool" if arrow_type == pa.bool_() and target == "boolean" else None
    if pg_type in _PG_TEXT_TYPES or pg_type in enum_types:
        ok = extension is None and pa.types.is_string(arrow_type) and target == "string"
        return "string" if ok else None
    if target in _NAIVE_DATETIME_DTYPES:
        if pg_type == "date" and arrow_type == pa.date32():
            return "date"
        if pg_type == "timestamp" and arrow_type == pa.timestamp("us"):
            return "timestamp"
        if pg_type == "timestamptz" and arrow_type == pa.timestamp("us", tz="UTC"):
            return "timestamptz"
        return None
    if pg_type == "uuid":
        return "uuid" if arrow_type == pa.binary(16) and target == "string" else None
    if pg_type in {"json", "jsonb"}:
        ok = json_ok and pa.types.is_string(arrow_type) and target == "object"
        return "json" if ok else None
    return None


def _check_range(values: pa.ChunkedArray, low: int, high: int, column: str) -> None:
    bounds = pc.min_max(values)
    low_value, high_value = bounds["min"].as_py(), bounds["max"].as_py()
    if low_value is not None and (low_value < low or high_value > high):
        raise _ConversionError(f"Column {column!r} has values outside the range psycopg reads")


def _float4_shortest_exclusive(value: np.float32) -> float:
    """PostgreSQL's float4 text for a value whose Arrow shortest text lies on a rounding bound.

    The shortest decimal strictly inside the rounding interval, closest to the value, ties to an
    even last digit; parsed into float64 as psycopg does.
    """
    exact_value = float(value)
    above = float(np.nextafter(value, np.float32(np.inf)))
    below = float(np.nextafter(value, np.float32(-np.inf)))
    with localcontext() as ctx:
        ctx.prec = 1200
        exact = Decimal(exact_value)
        low = (exact + Decimal(below)) / 2
        high = (exact + Decimal(above)) / 2
        exponent = exact.adjusted()
        for digits in range(1, 10):
            found = []
            for lead in (exponent, exponent + 1):
                quantum_exponent = lead - digits + 1
                quantum = Decimal(1).scaleb(quantum_exponent)
                for rounding in (ROUND_FLOOR, ROUND_CEILING):
                    candidate = exact.quantize(quantum, rounding=rounding)
                    if low < candidate < high:
                        last_digit_odd = int(candidate.scaleb(-quantum_exponent)) % 2
                        found.append((abs(candidate - exact), last_digit_odd, candidate))
            if found:
                return float(min(found, key=lambda item: (item[0], item[1]))[2])
    return exact_value


def _float4_to_float64(values: pa.ChunkedArray) -> np.ndarray:
    """float4 as psycopg returns it: PostgreSQL's shortest text parsed into float64."""
    array = values.combine_chunks()
    converted = pc.cast(pc.cast(array, pa.string()), pa.float64()).to_numpy(zero_copy_only=False)
    floats = array.fill_null(0).to_numpy(zero_copy_only=False).astype(np.float32, copy=False)
    with np.errstate(over="ignore", invalid="ignore"):
        exact = floats.astype(np.float64)
        above = np.nextafter(floats, np.float32(np.inf)).astype(np.float64)
        below = np.nextafter(floats, np.float32(-np.inf)).astype(np.float64)
        on_bound = np.isfinite(floats) & (
            (converted == (exact + above) / 2) | (converted == (exact + below) / 2)
        )
    positions = np.flatnonzero(on_bound)
    if positions.size:
        converted = np.array(converted, dtype=np.float64, copy=True)
        for position in positions:
            converted[position] = _float4_shortest_exclusive(floats[position])
    return converted


_UUID_HEX_POSITIONS = (0, 2, 4, 6, 9, 11, 14, 16, 19, 21, 24, 26, 28, 30, 32, 34)
_UUID_HEX_DIGITS = np.frombuffer(b"0123456789abcdef", dtype=np.uint8)


def _uuid_strings(values: pa.ChunkedArray) -> pa.Array:
    """Lower-case hyphenated text of fixed_size_binary(16) UUIDs, as ``str(uuid.UUID)``."""
    array = values.combine_chunks()
    count = len(array)
    if count in (0, array.null_count):
        return pa.nulls(count, type=pa.string())
    raw = np.frombuffer(array.buffers()[1], dtype=np.uint8)
    raw = raw[array.offset * 16 : (array.offset + count) * 16].reshape(count, 16)
    text = np.empty((count, 36), dtype=np.uint8)
    for byte_index, position in enumerate(_UUID_HEX_POSITIONS):
        text[:, position] = _UUID_HEX_DIGITS[raw[:, byte_index] >> 4]
        text[:, position + 1] = _UUID_HEX_DIGITS[raw[:, byte_index] & 0x0F]
    text[:, [8, 13, 18, 23]] = ord("-")
    offsets = np.arange(0, 36 * (count + 1), 36, dtype=np.int64)
    strings = pa.LargeStringArray.from_buffers(
        count, pa.py_buffer(offsets), pa.py_buffer(text.reshape(-1))
    ).cast(pa.string())
    if array.null_count:
        strings = pc.if_else(array.is_null(), pa.scalar(None, type=pa.string()), strings)
    return strings


def _string_series(values: pa.ChunkedArray | pa.Array) -> pd.Series:
    string_dtype = pd.api.types.pandas_dtype("string")
    return values.to_pandas(types_mapper={values.type: string_dtype}.get)


def _convert_column(  # noqa: PLR0911
    chunked: pa.ChunkedArray, name: str, converter: str, target: str
) -> Any:
    values = _storage(chunked)
    if converter == "int":
        return values.cast(pa.int64()).to_pandas(types_mapper=_INT64_DTYPE_MAPPER)
    if converter == "int_index":
        if values.null_count:
            raise _ConversionError(f"Helper index column {name!r} has NULL values")
        return values.cast(pa.int64()).to_numpy()
    if converter == "numeric_int":
        # numeric NaN becomes <NA> on the current path; Infinity, fractions and values outside
        # int64 fail the cast and re-read the segment through query_df.
        is_nan = pc.is_in(values, value_set=pa.array(["nan", "NaN"]))
        cleaned = pc.if_else(is_nan, pa.scalar(None, type=pa.string()), values)
        return cleaned.cast(pa.int64()).to_pandas(types_mapper=_INT64_DTYPE_MAPPER)
    if converter == "numeric_float":
        # Correctly rounded like float(Decimal); 'nan'/'inf'/'-inf' parse to NaN/+-inf.
        return values.cast(pa.float64()).to_pandas()
    if converter == "float4":
        return _float4_to_float64(values)
    if converter == "float8":
        return values.to_pandas()
    if converter == "bool":
        return values.to_pandas(types_mapper=_BOOLEAN_DTYPE_MAPPER)
    if converter == "string":
        values.validate(full=True)
        return _string_series(values)
    if converter == "uuid":
        return _string_series(_uuid_strings(values))
    if converter == "date":
        _check_range(values.cast(pa.int32()), _MIN_DATE_DAYS, _MAX_DATE_DAYS, name)
        # query_df gives date objects; to_datetime(utc=True) makes them datetime64[s].
        series = values.cast(pa.timestamp("s")).to_pandas()
        return series if target == "datetime64[s]" else series.astype(target)
    if converter in {"timestamp", "timestamptz"}:
        low, high = (
            (_MIN_TIMESTAMP_US, _MAX_TIMESTAMP_US)
            if converter == "timestamp"
            else (_MIN_TIMESTAMPTZ_US, _MAX_TIMESTAMPTZ_US)
        )
        _check_range(values.cast(pa.int64()), low, high, name)
        # Naive UTC wall clock in microseconds, as query_df's datetimes after to_datetime(utc=True).
        series = values.cast(pa.timestamp("us")).to_pandas()
        return series if target == "datetime64[us]" else series.astype(target)
    if converter == "json":
        values.validate(full=True)
        loads = json.loads
        parsed = [None if value is None else loads(value) for value in values.to_pylist()]
        # The same per-column inference pd.DataFrame(rows) applies to psycopg's json values.
        return pd.DataFrame([(value,) for value in parsed])[0]
    raise _ConversionError(f"Unknown converter {converter!r}")


def _arrow_table_to_frame(table: pa.Table, arrow_plan: _ArrowPlan) -> pd.DataFrame:
    if _schema_signature(table.schema) != arrow_plan.signature:
        raise _ConversionError("Arrow result schema differs from the described schema")
    names = table.column_names
    if table.num_rows == 0:
        return pd.DataFrame(columns=names)
    columns = list(table.columns)
    del table
    converted: dict[str, Any] = {}
    for position, name in enumerate(names):
        chunked = columns[position]
        # Drop the Arrow column as soon as it is converted to keep the peak memory down.
        columns[position] = None
        spec = arrow_plan.converters.get(name)
        if spec is not None:
            converted[name] = _convert_column(chunked, name, *spec)
        del chunked
    return pd.DataFrame(converted, copy=False)


def _close_quietly(connection: Any) -> None:
    try:
        connection.close()
    except Exception:  # closing a broken connection must not mask the real error
        logger.debug("Closing an ADBC PostgreSQL connection failed", exc_info=True)


def _fetch_one_row(connection: Any, sql: str) -> dict[str, Any]:
    cursor = connection.cursor()
    try:
        cursor.execute(sql)
        rows = cursor.fetch_arrow_table().to_pylist()
    finally:
        cursor.close()
    if len(rows) != 1:
        raise _ConversionError(f"Expected one row, got {len(rows)}")
    return rows[0]


def _normalize_fingerprint(row: Mapping[str, Any]) -> dict[str, str]:
    return {str(key): str(value) for key, value in row.items()}


def _open_adbc_connection(conninfo: str, expected_fingerprint: Mapping[str, str]) -> Any:
    """Open an autocommit ADBC connection whose session matches the SQLAlchemy session.

    The probe query runs through ADBC's binary COPY, so a server without
    ``COPY ... TO STDOUT (FORMAT binary)`` fails here too.
    """
    try:
        connection = _adbc_dbapi.connect(conninfo, autocommit=True)
    except _AdbcError as exc:
        raise _ConnectionFailure(f"cannot connect: {exc}") from exc
    try:
        fingerprint = _normalize_fingerprint(_fetch_one_row(connection, _SESSION_SQL))
    except BaseException as exc:
        _close_quietly(connection)
        if isinstance(exc, (_AdbcError, _ConversionError, *_ARROW_ERRORS)):
            raise _ConnectionFailure(f"session probe failed: {exc}") from exc
        raise
    if fingerprint != dict(expected_fingerprint):
        _close_quietly(connection)
        differing = sorted(
            key for key in expected_fingerprint if fingerprint.get(key) != expected_fingerprint[key]
        )
        raise _ConnectionFailure(f"the ADBC session differs from the SQLAlchemy one in {differing}")
    return connection


class _AdbcConnectionPool:
    """Idle ADBC connections of one executor, each lent to one segment query at a time.

    A connection whose query failed or was interrupted is closed, never reused. Idle connections
    close ``idle_close_delay`` seconds after the last running query finished, or when the
    executor is garbage-collected or the process exits.
    """

    def __init__(self, max_idle: int, idle_close_delay: float) -> None:
        self._max_idle = max(1, max_idle)
        self._idle_close_delay = idle_close_delay
        self._connect: Callable[[], Any] | None = None
        self._idle: list[Any] = []
        self._active = 0
        self._timer: threading.Timer | None = None
        self._generation = 0
        self._lock = threading.Lock()

    def configure(self, connect: Callable[[], Any]) -> None:
        with self._lock:
            self._connect = connect

    @contextmanager
    def acquire(self) -> Iterator[Any]:
        with self._lock:
            if self._connect is None:
                raise _ConnectionFailure("the connection pool is not configured")
            connect = self._connect
            connection = self._idle.pop() if self._idle else None
            self._active += 1
            self._cancel_timer_locked()
        if connection is None:
            try:
                connection = connect()
            except BaseException:
                self._release(None)
                raise
        try:
            yield connection
        except BaseException:
            _close_quietly(connection)
            self._release(None)
            raise
        self._release(connection)

    def _release(self, connection: Any | None) -> None:
        surplus = None
        with self._lock:
            self._active -= 1
            if connection is not None:
                if len(self._idle) < self._max_idle:
                    self._idle.append(connection)
                else:
                    surplus = connection
            if self._active == 0 and self._idle:
                self._schedule_close_locked()
        if surplus is not None:
            _close_quietly(surplus)

    def _cancel_timer_locked(self) -> None:
        self._generation += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _schedule_close_locked(self) -> None:
        self._cancel_timer_locked()
        timer = threading.Timer(
            self._idle_close_delay, self._close_idle_if_unused, args=(self._generation,)
        )
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _close_idle_if_unused(self, generation: int) -> None:
        with self._lock:
            if self._active or generation != self._generation:
                return
            idle, self._idle = self._idle, []
            self._timer = None
        for connection in idle:
            _close_quietly(connection)

    def idle_count(self) -> int:
        with self._lock:
            return len(self._idle)

    def close(self) -> None:
        with self._lock:
            self._cancel_timer_locked()
            idle, self._idle = self._idle, []
        for connection in idle:
            _close_quietly(connection)


def _is_small_read(plan: ReadV3Plan) -> bool:
    """A plan with a known row count below ``_MIN_ARROW_ROWS`` (``None`` is not small)."""
    return plan.total_rows is not None and plan.total_rows < _MIN_ARROW_ROWS


def _live_options(driver_connection: Any) -> dict[str, tuple[str | None, str | None, str | None]]:
    """libpq options of a psycopg connection: keyword -> (value, compiled default, env var)."""

    def _text(value: bytes | None) -> str | None:
        return value.decode("utf-8") if value is not None else None

    return {
        _text(option.keyword): (_text(option.val), _text(option.compiled), _text(option.envvar))
        for option in driver_connection.pgconn.info
    }


def _with_connect_timeout(
    built: dict[str, str], live: Mapping[str, tuple[str | None, str | None, str | None]]
) -> dict[str, str]:
    """``built`` plus ``connect_timeout`` set outside the URL (``connect_args``), which DVT's
    engine factory does for PostgreSQL."""
    timeout = live.get("connect_timeout", (None, None, None))[0]
    if "connect_timeout" in built or timeout is None:
        return built
    return {**built, "connect_timeout": timeout}


def _differing_options(
    live: Mapping[str, tuple[str | None, str | None, str | None]],
    reference: Mapping[str, tuple[str | None, str | None, str | None]],
) -> list[str]:
    """libpq options whose values differ between the SQLAlchemy connection (``live``) and a
    connection opened from the URL-built conninfo alone (``reference``).

    Both are opened by the same libpq in the same process, so defaults libpq derives itself
    (``sslcertmode``), environment variables and a password file give equal values; what
    differs was set outside the URL (``connect_args``, an engine ``creator``, events).
    """
    keys = (set(live) | set(reference)) - _IGNORED_LIVE_OPTIONS
    absent = (None, None, None)
    return sorted(key for key in keys if live.get(key, absent)[0] != reference.get(key, absent)[0])


class PostgresReadExecutor(SQLReadExecutor):
    def __init__(
        self,
        engine: Engine,
        *,
        dialect: SQLDialect | None = None,
        max_concurrent_queries: int | None = None,
    ):
        super().__init__(engine, dialect=dialect, max_concurrent_queries=max_concurrent_queries)
        self._arrow_lock = threading.RLock()
        self._arrow_off_reason: str | None = None if adbc_available() else "ADBC is not installed"
        self._session: _SessionInfo | None = None
        self._plans: dict[int, tuple[ReadV3Plan, _ArrowPlan | None]] = {}
        self._pool = _AdbcConnectionPool(
            max_idle=max_concurrent_queries or _DEFAULT_CONNECTION_POOL_SIZE,
            idle_close_delay=_IDLE_CLOSE_DELAY_SEC,
        )
        weakref.finalize(self, self._pool.close)

    # ----- decisions -------------------------------------------------------------------------

    def _scrub(self, value: object) -> str:
        text = str(value)
        password = self.engine.url.password
        if password:
            text = text.replace(password, "***")
        return text[:500]

    def _switch_off(self, plan: ReadV3Plan, reason: str, *, warn: bool) -> None:
        with self._arrow_lock:
            if self._arrow_off_reason is not None:
                return
            self._arrow_off_reason = reason
        self._pool.close()
        log = logger.warning if warn else logger.info
        log(
            "read_v3 PostgreSQL Arrow path is off for this read of %s: %s; segments are read "
            "through query_df",
            plan.source_name(),
            self._scrub(reason),
        )

    def _static_ineligibility(self, plan: ReadV3Plan) -> str | None:
        if _is_small_read(plan):
            return f"{plan.total_rows} rows < {_MIN_ARROW_ROWS}"
        if self._uses_exact_decimal_index(plan):
            return "the range index keeps exact Decimal key values"
        for column in plan.output_columns:
            type_repr = (plan.output_column_type_repr.get(column) or "").lower().strip()
            if (
                type_repr.startswith("_")
                or "[]" in type_repr
                or "array" in type_repr
                or "interval" in type_repr
                or "bytea" in type_repr
                or (type_repr.startswith("time") and not type_repr.startswith("timestamp"))
            ):
                return f"column {column!r} has type {type_repr!r}"
            try:
                self._dtype_for_column(plan, column)
            except ReadV3ExecutionError:
                return f"column {column!r} has no read_v3 dtype"
        if (
            plan.strategy == PartitionStrategy.RANGE
            and plan.index_column_name == plan.partition_key_alias
            and plan.index_column_name not in plan.output_columns
            and not self._is_integer_type_repr(plan.partition_key_type_repr)
        ):
            return f"the helper index has the non-integer type {plan.partition_key_type_repr!r}"
        return None

    def _probe_session(self) -> _SessionInfo | str:  # noqa: PLR0911
        """Map the engine URL to a libpq conninfo and capture the session to reproduce."""
        try:
            import psycopg
            from psycopg.conninfo import conninfo_to_dict, make_conninfo
        except ImportError:
            return "psycopg is not installed"
        if self.engine.dialect.driver != "psycopg":
            return f"driver {self.engine.dialect.driver!r} is not psycopg 3"
        cargs, cparams = self.engine.dialect.create_connect_args(self.engine.url)
        if any(cargs):
            return "the engine passes a positional DSN"
        params = {key: value for key, value in cparams.items() if key != "context"}
        try:
            built = conninfo_to_dict(make_conninfo("", **params))
        except Exception:  # psycopg raises ProgrammingError for unknown options
            return "the URL parameters are not libpq connection options"
        with self.engine.connect() as connection:
            row = execute_literal_sql(connection, _SESSION_SQL).mappings().one()
            live = _live_options(connection.connection.driver_connection)
        built = _with_connect_timeout(built, live)
        try:
            with psycopg.connect(make_conninfo("", **built), autocommit=True) as reference:
                reference_options = _live_options(reference)
        except psycopg.Error as exc:
            return f"connecting with the URL parameters alone failed: {type(exc).__name__}"
        differing = _differing_options(live, reference_options)
        if differing:
            return f"connection parameters set outside the URL: {differing}"
        fingerprint = _normalize_fingerprint(row)
        if int(fingerprint["server_version_num"]) < 120000:
            return f"PostgreSQL server_version_num {fingerprint['server_version_num']} < 120000"
        if fingerprint["client_encoding"] != "UTF8" or fingerprint["server_encoding"] == "SQL_ASCII":
            return (
                f"client_encoding {fingerprint['client_encoding']!r}, "
                f"server_encoding {fingerprint['server_encoding']!r}"
            )
        if not fingerprint["date_style"].startswith("ISO"):
            return f"DateStyle {fingerprint['date_style']!r}"
        return _SessionInfo(
            conninfo=make_conninfo("", **built),
            fingerprint=fingerprint,
            float4_text_ok=fingerprint["float4_text"] == _FLOAT4_PROBE,
            float8_text_ok=fingerprint["float8_text"] == _FLOAT8_PROBE,
        )

    def _enum_types(self, cursor: Any, schema: pa.Schema) -> frozenset[str]:
        enum_types = set()
        for arrow_field in schema:
            pg_type = _pg_type_name(arrow_field)
            if (
                pg_type
                and pg_type not in _PG_BUILTIN_TYPES
                and pa.types.is_string(arrow_field.type)
            ):
                cursor.execute(_ENUM_SQL, (pg_type,))
                if cursor.fetch_arrow_table().to_pylist()[0]["is_enum"]:
                    enum_types.add(pg_type)
        return frozenset(enum_types)

    def _build_arrow_plan(
        self,
        plan: ReadV3Plan,
        schema: pa.Schema,
        session: _SessionInfo,
        enum_types: frozenset[str],
    ) -> _ArrowPlan | str:
        names = list(schema.names)
        if len(set(names)) != len(names):
            return f"duplicate result column names {names!r}"
        result_columns = pd.Index(names)
        output_by_result: dict[str, str] = {}
        for output_column in plan.output_columns:
            resolved = self._resolve_column_name(result_columns, output_column)
            if resolved is None or resolved in output_by_result:
                return f"output column {output_column!r} does not map to one result column"
            output_by_result[resolved] = output_column
        try:
            index_column = self._pick_index_column(plan, pd.DataFrame(columns=names))
        except ReadV3ExecutionError as exc:
            return str(exc)
        json_ok = getattr(self.engine.dialect, "_json_deserializer", None) is None
        converters: dict[str, tuple[str, str]] = {}
        for arrow_field in schema:
            name = arrow_field.name
            if name in output_by_result:
                target = self._dtype_for_column(plan, output_by_result[name])
                index_helper = False
            elif name == index_column:
                target, index_helper = "int64", True
            else:
                continue
            converter = _converter_for(
                arrow_field,
                target,
                index_helper=index_helper,
                enum_types=enum_types,
                session=session,
                json_ok=json_ok,
            )
            if converter is None:
                return (
                    f"column {name!r}: PostgreSQL type {_pg_type_name(arrow_field)!r}, "
                    f"Arrow type {arrow_field.type}, dtype {target!r}"
                )
            converters[name] = (converter, target)
        return _ArrowPlan(signature=_schema_signature(schema), converters=converters)

    def _decide(self, plan: ReadV3Plan, sql: str) -> _ArrowPlan | None:
        reason = self._static_ineligibility(plan)
        if reason is None:
            if self._session is None:
                try:
                    probed = self._probe_session()
                except Exception as exc:  # the current path reports engine errors
                    probed = f"probing the SQLAlchemy session failed: {type(exc).__name__}: {exc}"
                if isinstance(probed, str):
                    self._switch_off(plan, probed, warn=False)
                    return None
                self._session = probed
                self._pool.configure(
                    partial(_open_adbc_connection, probed.conninfo, probed.fingerprint)
                )
            try:
                with self._pool.acquire() as connection:
                    cursor = connection.cursor()
                    try:
                        schema = cursor.adbc_execute_schema(sql)
                        enum_types = self._enum_types(cursor, schema)
                    finally:
                        cursor.close()
            except _ConnectionFailure as exc:
                self._switch_off(plan, str(exc), warn=True)
                return None
            except (_AdbcError, *_ARROW_ERRORS) as exc:
                reason = f"describing the segment query failed: {type(exc).__name__}: {exc}"
            else:
                built = self._build_arrow_plan(plan, schema, self._session, enum_types)
                if isinstance(built, _ArrowPlan):
                    return built
                reason = built
        log = logger.debug if _is_small_read(plan) else logger.info  # small reads are common
        log(
            "read_v3 PostgreSQL segments of %s are read through query_df: %s",
            plan.source_name(),
            self._scrub(reason),
        )
        return None

    def _arrow_plan(self, plan: ReadV3Plan, sql: str) -> _ArrowPlan | None:
        with self._arrow_lock:
            if self._arrow_off_reason is not None:
                return None
            cached = self._plans.get(id(plan))
            if cached is not None and cached[0] is plan:
                return cached[1]
            arrow_plan = self._decide(plan, sql)
            self._plans[id(plan)] = (plan, arrow_plan)
            return arrow_plan if self._arrow_off_reason is None else None

    # ----- fetch -----------------------------------------------------------------------------

    def _fetch_arrow_table(self, sql: str) -> pa.Table:
        with self._pool.acquire() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(sql)
                return cursor.fetch_arrow_table()
            finally:
                cursor.close()

    def _fetch_segment_df(self, sql: str, plan: ReadV3Plan) -> pd.DataFrame:
        arrow_plan = self._arrow_plan(plan, sql)
        if arrow_plan is None:
            return super()._fetch_segment_df(sql, plan)
        try:
            return _arrow_table_to_frame(self._fetch_arrow_table(sql), arrow_plan)
        except _ConnectionFailure as exc:
            self._switch_off(plan, str(exc), warn=True)
        except (_AdbcError, *_ARROW_ERRORS, ValueError, TypeError, OverflowError) as exc:
            logger.warning(
                "read_v3 PostgreSQL Arrow result of %s is re-read through query_df: %s: %s",
                plan.source_name(),
                type(exc).__name__,
                self._scrub(exc),
            )
        return super()._fetch_segment_df(sql, plan)
