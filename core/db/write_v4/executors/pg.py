"""PostgreSQL (psycopg 3) write_v4 executor: one ``COPY ... FROM STDIN (FORMAT csv)`` per partition.

``SQLWriteExecutor`` inserts through psycopg ``executemany``, which spends its time in per-value
Python code under the GIL (~41k rows/s per core). This executor overrides only ``_insert_partition``: a partition is converted
column by column to Arrow, encoded by ``pyarrow.csv`` into buffers of ``copy_buffer_rows`` rows
and streamed into a single COPY in one transaction. ``append`` copies into the target,
``truncate``/``upsert`` into the staging table of ``SQLWriteExecutor``. A write whose target
takes COPY runs ``request.bulk_write_workers`` partitions at once when that is more than
``request.write_workers`` (the node resolves it; ``core/db/concurrency.py`` has the measurements).

Every value is stored as the ``executemany`` path stores it (see ``_build_copy_array``). Anything
without that guarantee goes through the inherited path:

- a column whose type is outside ``COPY_TYPE_KINDS`` (json, arrays, bytea, interval, time, enum,
  domains, ...), a target that is not a plain or partitioned table or has INSERT rules (COPY
  ignores rules), a default-only insert: the whole write;
- a partition with a source column the conversion matrix does not cover with parity (for
  example ``inf`` into numeric, bool into integer, an aware datetime with an unknown session time
  zone): that partition;
- a server that rejects ``COPY FROM STDIN`` itself (SQLSTATE ``0A000`` or ``42601``, for example
  row-level security or a PostgreSQL-compatible engine) or a ``SQL_ASCII`` client encoding: the
  rest of the write, with one warning.

Data errors raised by the server during COPY (constraints, bad values) are not retried: they
become ``WriteV4ExecutionError`` with the partition-relative row and the column, and the
partition's transaction leaves nothing behind.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from threading import RLock
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import dask.dataframe as dd
import numpy as np
import pandas as pd
import psycopg
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pa_csv
import sqlalchemy as sa

from core.db.write_v4.batching import rows_for_bytes
from core.db.write_v4.errors import WriteV4ExecutionError
from core.db.write_v4.executors.sql import SQLWriteExecutor
from core.db.write_v4.models import WritePlan, WriteRequest, WriteResult
from core.db.write_v4.normalize import ColumnAlignment, align_partition_to_table

logger = logging.getLogger(__name__)

# Column kinds by ``pg_catalog`` base type name. Other types (and domains over these) use
# ``executemany``.
COPY_TYPE_KINDS: dict[str, str] = {
    "int2": "int",
    "int4": "int",
    "int8": "int",
    "float4": "float4",
    "float8": "float8",
    "numeric": "numeric",
    "bool": "bool",
    "text": "text",
    "varchar": "text",
    "bpchar": "text",
    "date": "date",
    "timestamp": "timestamp",
    "timestamptz": "timestamptz",
    "uuid": "uuid",
}
# Relation kinds COPY FROM writes like INSERT: ordinary and partitioned tables.
_COPY_RELKINDS = frozenset({"r", "p"})
# SQLSTATEs of a COPY statement the server rejects as a whole: feature_not_supported (row-level
# security, engines without COPY FROM STDIN) and syntax_error (no option list syntax).
_COPY_UNSUPPORTED_SQLSTATES = frozenset({"0A000", "42601"})
_COPY_CONTEXT_RE = re.compile(r"^COPY .*?, line (\d+)(.*)$", re.DOTALL)
# Arrow bytes of the rows of one CSV buffer without ``WriteRequest.rows_per_batch`` (see
# ``copy_buffer_rows``; measurements in ``core/db/concurrency.py``).
COPY_BUFFER_BYTES = 4 * 1024 * 1024
# 15 significant digits: PostgreSQL ``float8_numeric`` formats the float8 with ``%.15g``.
_FLOAT8_NUMERIC_DIGITS = 15
# A normal double whose shortest repr has <= 15 digits prints the same value with ``%.15g``.
_SHORTEST_REPR_SAFE_ABS = (1e-300, 1e300)
_MIN_TIMESTAMP_US = np.datetime64("0001-01-01T00:00:00", "us")
_MAX_TIMESTAMP_US = np.datetime64("9999-12-31T23:59:59.999999", "us")
_CATALOG_SQL = sa.text(
    """
    SELECT c.relkind::text AS relkind,
           EXISTS (
               SELECT 1 FROM pg_catalog.pg_rewrite r
               WHERE r.ev_class = c.oid AND r.ev_type = '3'
           ) AS has_insert_rules,
           a.attname::text AS column_name,
           t.typname::text AS type_name,
           t.typtype::text AS type_type,
           n.nspname::text AS type_schema
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_attribute a
      ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
    JOIN pg_catalog.pg_type t ON t.oid = a.atttypid
    JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
    WHERE c.oid = pg_catalog.to_regclass(:relation)
    """
)


class _CopyConversionError(Exception):
    """A partition column cannot be converted with executemany parity; use executemany."""


class _CopyUnsupportedError(Exception):
    """The server or session cannot take COPY FROM STDIN; use executemany for the write."""


@dataclass(frozen=True)
class CopyTarget:
    """COPY eligibility of one relation: ``kinds`` maps COPY-able columns to their kind."""

    kinds: dict[str, str]
    type_names: dict[str, str]
    reason: str | None = None

    def unsupported_columns(self, column_names: list[str]) -> list[str]:
        return [name for name in column_names if name not in self.kinds]


def copy_type_kind(type_name: str, type_type: str, type_schema: str) -> str | None:
    """COPY kind of a column type from ``pg_type``; ``None`` keeps the write on executemany."""
    if type_type != "b" or type_schema != "pg_catalog":
        return None
    return COPY_TYPE_KINDS.get(type_name)


def build_copy_target(rows: list[dict[str, object]]) -> CopyTarget:
    """``CopyTarget`` from the catalog rows of ``_CATALOG_SQL`` (one row per column)."""
    if not rows:
        return CopyTarget({}, {}, reason="relation not found in pg_class")
    relkind = str(rows[0]["relkind"])
    type_names = {str(row["column_name"]): str(row["type_name"]) for row in rows}
    if relkind not in _COPY_RELKINDS:
        return CopyTarget({}, type_names, reason=f"relation kind {relkind!r} is not a table")
    if rows[0]["has_insert_rules"]:
        return CopyTarget({}, type_names, reason="the table has INSERT rules, which COPY ignores")
    kinds: dict[str, str] = {}
    for row in rows:
        kind = copy_type_kind(str(row["type_name"]), str(row["type_type"]), str(row["type_schema"]))
        if kind is not None:
            kinds[str(row["column_name"])] = kind
    return CopyTarget(kinds, type_names)


def copy_buffer_rows(rows_per_batch: int | None, arrow_table: pa.Table) -> int:
    """Rows per CSV buffer: ``rows_per_batch``, or about ``COPY_BUFFER_BYTES`` of the partition's
    Arrow data (at most the whole partition).

    The buffer size bounds the CSV memory of a partition and barely affects speed: 1000-row
    buffers cost within 2% of 10k-100k-row ones (1M wide_mixed rows in the Linux container, 1 and
    4 threads), while peak memory grows with it (wide rows: 3.3 GB at 164 MB buffers, 2.0 GB at
    4 MB); a partition is one COPY either way.
    """
    if rows_per_batch:
        return rows_per_batch
    total_rows = max(1, arrow_table.num_rows)
    return rows_for_bytes(COPY_BUFFER_BYTES, arrow_table.nbytes // total_rows, max_rows=total_rows)


@dataclass(frozen=True)
class CopySession:
    """Session parameters of the COPY connection that the conversion depends on."""

    timezone: str | None

    def zone(self) -> ZoneInfo:
        """Session ``TimeZone`` as a ``ZoneInfo``; unknown names keep executemany."""
        if not self.timezone:
            raise _CopyConversionError("the session TimeZone is not reported by the server")
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError, OSError) as exc:
            raise _CopyConversionError(
                f"session TimeZone {self.timezone!r} is not a known IANA zone"
            ) from exc


class PostgresWriteExecutor(SQLWriteExecutor):
    def __init__(self, engine: sa.Engine, dialect) -> None:
        super().__init__(engine, dialect)
        self._lock = RLock()
        self._copy_targets: dict[str, CopyTarget] = {}
        self._copy_disabled_reason: str | None = None
        self._warned: set[str] = set()

    def execute(self, ddf: dd.DataFrame, request: WriteRequest, plan: WritePlan) -> WriteResult:
        workers = self._copy_write_workers(ddf, request)
        if workers != request.write_workers:
            logger.info(
                "write_v4 PostgreSQL COPY: write workers %s -> %s", request.write_workers, workers
            )
            request = request.model_copy(update={"write_workers": workers})
        return super().execute(ddf, request, plan)

    def _copy_write_workers(self, ddf: dd.DataFrame, request: WriteRequest) -> int:
        """``request.bulk_write_workers`` when the target takes COPY and it is more, else
        ``request.write_workers``.

        ``None`` (an explicit worker setting, see ``resolve_bulk_write_workers``) keeps the write
        workers. A write that goes through executemany as a whole keeps them too: more threads
        slow it.
        """
        bulk = request.bulk_write_workers
        if bulk is None or bulk <= request.write_workers or self._copy_disabled_reason is not None:
            return request.write_workers
        table = self._reflect_table(request.target.table_name, request.target.schema_name)
        alignment = align_partition_to_table(
            ddf._meta, table, request, include_default_only_diagnostic=False, cast_to_object=False
        )
        if not alignment.insert_column_names or self._usable_target(table, alignment) is None:
            return request.write_workers
        return bulk

    def _insert_partition(self, table: sa.Table, pdf: pd.DataFrame, request: WriteRequest) -> int:
        if self._copy_disabled_reason is not None:
            return super()._insert_partition(table, pdf, request)
        alignment = align_partition_to_table(pdf, table, request, cast_to_object=False)
        if alignment.row_count == 0:
            return 0
        # Default-only rows have no columns to COPY: the inherited INSERT ... DEFAULT VALUES.
        target = None if alignment.default_only_insert else self._usable_target(table, alignment)
        if target is not None:
            try:
                return self._copy_partition(table, target, alignment, request)
            except _CopyConversionError as exc:
                self._warn_once(
                    f"conversion:{table.fullname}:{exc}",
                    f"write_v4 PostgreSQL COPY partition of {table.fullname} goes through "
                    f"executemany: {exc}",
                )
            except _CopyUnsupportedError as exc:
                with self._lock:
                    self._copy_disabled_reason = str(exc)
                self._warn_once(
                    "unsupported",
                    f"write_v4 PostgreSQL COPY is unavailable, the rest of the write uses "
                    f"executemany: {exc}",
                )
        return super()._insert_partition(table, pdf, request)

    def _usable_target(self, table: sa.Table, alignment: ColumnAlignment) -> CopyTarget | None:
        """The COPY target when the relation and every inserted column allow COPY, else None."""
        target = self._copy_target(table)
        if target is None:
            return None
        unsupported = target.unsupported_columns(alignment.insert_column_names)
        if target.reason is None and not unsupported:
            return target
        reason = target.reason or ", ".join(
            f"{name} ({target.type_names.get(name, '?')})" for name in unsupported
        )
        self._warn_once(
            f"target:{table.fullname}",
            f"write_v4 PostgreSQL COPY is not used for {table.fullname}: {reason}; "
            "rows go through executemany",
        )
        return None

    def _copy_target(self, table: sa.Table) -> CopyTarget | None:
        key = table.fullname
        with self._lock:
            if key in self._copy_targets:
                return self._copy_targets[key]
            relation = self.dialect.full_table_name(table.name, table.schema)
            try:
                with self.engine.connect() as conn:
                    rows = [
                        dict(row._mapping)
                        for row in conn.execute(_CATALOG_SQL, {"relation": relation})
                    ]
            except sa.exc.DBAPIError as exc:
                self._copy_disabled_reason = f"catalog lookup failed: {exc.orig or exc}"
                self._warn_once(
                    "catalog",
                    f"write_v4 PostgreSQL COPY is unavailable, the write uses executemany: "
                    f"{self._copy_disabled_reason}",
                )
                return None
            target = build_copy_target(rows)
            self._copy_targets[key] = target
            return target

    def _copy_partition(
        self,
        table: sa.Table,
        target: CopyTarget,
        alignment: ColumnAlignment,
        request: WriteRequest,
    ) -> int:
        columns = alignment.insert_column_names
        frame = alignment.normalized
        statement = self._copy_statement(table, columns)
        with self.engine.begin() as conn:
            driver = conn.connection.driver_connection
            if driver.info.encoding == "ascii":
                raise _CopyUnsupportedError("client_encoding SQL_ASCII")
            session = CopySession(timezone=driver.info.parameter_status("TimeZone"))
            arrow_table = build_copy_table(frame, columns, target.kinds, session, table.fullname)
            buffer_rows = copy_buffer_rows(request.rows_per_batch, arrow_table)
            copy_started = False
            try:
                with driver.cursor() as cursor, cursor.copy(statement) as copy:
                    copy_started = True
                    for buffer in iter_csv_buffers(arrow_table, buffer_rows):
                        copy.write(buffer)
            except psycopg.Error as exc:
                if not copy_started and exc.sqlstate in _COPY_UNSUPPORTED_SQLSTATES:
                    raise _CopyUnsupportedError(
                        f"{exc.sqlstate}: {exc.diag.message_primary or exc}"
                    ) from exc
                raise copy_data_error(exc, table.fullname, columns) from exc
        return alignment.row_count

    def _copy_statement(self, table: sa.Table, columns: list[str]) -> str:
        quoted_columns = ", ".join(self.dialect.quote_ident(name) for name in columns)
        target = self.dialect.full_table_name(table.name, table.schema)
        # Arrow quotes every string value and writes NULL as an unquoted empty field, so NULL ''
        # and quoted "" (empty string) are distinct; Arrow always writes UTF-8.
        return (
            f"COPY {target} ({quoted_columns}) FROM STDIN "
            "(FORMAT csv, DELIMITER ',', QUOTE '\"', NULL '', ENCODING 'UTF8')"
        )

    def _warn_once(self, key: str, message: str) -> None:
        with self._lock:
            if key in self._warned:
                return
            self._warned.add(key)
        logger.warning(message)


# CSV options for COPY: no header; "needed" quotes every string-typed value (so an empty string is
# "" and never the NULL marker) and leaves numbers, booleans, dates and timestamps unquoted.
_CSV_WRITE_OPTIONS = pa_csv.WriteOptions(include_header=False, quoting_style="needed")


def iter_csv_buffers(arrow_table: pa.Table, buffer_rows: int):
    """CSV encodings of consecutive ``buffer_rows`` slices of ``arrow_table`` as memoryviews."""
    for start in range(0, arrow_table.num_rows, buffer_rows):
        sink = pa.BufferOutputStream()
        pa_csv.write_csv(arrow_table.slice(start, buffer_rows), sink, _CSV_WRITE_OPTIONS)
        yield memoryview(sink.getvalue())


def copy_data_error(
    exc: psycopg.Error, table_name: str, columns: list[str]
) -> WriteV4ExecutionError:
    """``WriteV4ExecutionError`` naming the partition row and column of a COPY data error."""
    line, column = _copy_error_location(exc, columns)
    where = f" at row {line} of the partition" if line is not None else ""
    if column:
        where += f", column {column!r}"
    detail = exc.diag.message_detail
    message = exc.diag.message_primary or str(exc).strip()
    return WriteV4ExecutionError(
        f"PostgreSQL COPY into '{table_name}' failed{where}: {message}"
        + (f" ({detail})" if detail else "")
        + ". The partition transaction was rolled back; no rows of this partition were written."
    )


def _copy_error_location(exc: psycopg.Error, columns: list[str]) -> tuple[int | None, str | None]:
    column = exc.diag.column_name
    for context_line in (exc.diag.context or "").splitlines():
        match = _COPY_CONTEXT_RE.match(context_line)
        if not match:
            continue
        line = int(match.group(1))
        rest = match.group(2)
        if column is None and rest.startswith(", column "):
            named = rest[len(", column ") :]
            # Column names may contain ":" or ", ": take the longest known name before ":".
            candidates = [name for name in columns if named.startswith(f"{name}:")]
            if candidates:
                column = max(candidates, key=len)
        return line, column
    return None, column


# ---------------------------------------------------------------------------------------------
# Partition conversion
# ---------------------------------------------------------------------------------------------

# Values Arrow cannot take with the expected type (out-of-range Python ints, mixed objects).
_ARROW_CONVERSION_ERRORS = (
    pa.ArrowInvalid,
    pa.ArrowNotImplementedError,
    pa.ArrowTypeError,
    OverflowError,
    TypeError,
    ValueError,
)


def build_copy_table(
    frame: pd.DataFrame,
    columns: list[str],
    kinds: dict[str, str],
    session: CopySession,
    table_name: str,
) -> pa.Table:
    """Arrow table whose CSV text stores the executemany values of every column."""
    arrays = []
    for name in columns:
        series = frame[name]
        try:
            array = _build_copy_array(series, kinds[name], session)
        except _CopyConversionError as exc:
            raise _CopyConversionError(f"column {name!r}: {exc}") from exc
        except _ARROW_CONVERSION_ERRORS as exc:
            raise _CopyConversionError(f"column {name!r}: {exc}") from exc
        if pa.types.is_string(array.type) or pa.types.is_large_string(array.type):
            _reject_nul(array, name, table_name)
        arrays.append(array)
    return pa.Table.from_arrays(arrays, names=columns)


def _reject_nul(array: pa.Array, column: str, table_name: str) -> None:
    has_nul = pc.match_substring(array, "\x00")
    if not pc.any(has_nul).as_py():
        return
    row = int(np.flatnonzero(has_nul.to_numpy(zero_copy_only=False))[0]) + 1
    raise WriteV4ExecutionError(
        f"Column {column!r} of '{table_name}' contains a NUL (0x00) character at row {row} of "
        "the partition: PostgreSQL text values cannot contain NUL bytes."
    )


def source_kind(series: pd.Series) -> str:  # noqa: PLR0911
    """Kind of a source column: int, float, bool, string, datetime, datetime_tz, date, decimal,
    decimal_arrow, uuid or other (no COPY conversion)."""
    dtype = series.dtype
    if isinstance(dtype, pd.ArrowDtype):
        arrow_type = dtype.pyarrow_dtype
        if pa.types.is_integer(arrow_type):
            return "int"
        if pa.types.is_floating(arrow_type):
            return "float"
        if pa.types.is_boolean(arrow_type):
            return "bool"
        if pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
            return "string"
        if pa.types.is_date(arrow_type):
            return "date"
        if pa.types.is_decimal(arrow_type):
            return "decimal_arrow"
        return "other"
    if isinstance(dtype, pd.StringDtype):
        return "string"
    if isinstance(dtype, pd.DatetimeTZDtype):
        return "datetime_tz"
    if isinstance(dtype, pd.CategoricalDtype):
        return "other"
    if pd.api.types.is_bool_dtype(dtype):
        return "bool"
    if pd.api.types.is_integer_dtype(dtype):
        return "int"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    if pd.api.types.is_datetime64_dtype(dtype):
        return "datetime"
    if pd.api.types.is_object_dtype(dtype):
        return _object_kind(series)
    return "other"


_OBJECT_KINDS = {
    "string": "string",
    "empty": "string",
    "integer": "int",
    "floating": "float",
    "boolean": "bool",
    "decimal": "decimal",
    "date": "date",
    "datetime": "datetime_object",
    "datetime64": "datetime_object",
}


def _object_kind(series: pd.Series) -> str:
    inferred = pd.api.types.infer_dtype(series, skipna=True)
    kind = _OBJECT_KINDS.get(inferred)
    if kind is not None:
        return kind
    values = series[series.notna()]
    if len(values) and all(isinstance(value, UUID) for value in values):
        return "uuid"
    return "other"


# Accepted source kinds per target kind; any other combination keeps executemany.
_ACCEPTED_SOURCES: dict[str, frozenset[str]] = {
    "int": frozenset({"int", "float", "string"}),
    "float8": frozenset({"int", "float", "decimal", "decimal_arrow", "string"}),
    "float4": frozenset({"int", "float", "decimal", "decimal_arrow", "string"}),
    "numeric": frozenset({"int", "float", "decimal", "decimal_arrow", "string"}),
    "bool": frozenset({"bool"}),
    "text": frozenset({"string", "int", "bool"}),
    "date": frozenset({"datetime", "datetime_tz", "datetime_object", "date", "string"}),
    "timestamp": frozenset({"datetime", "datetime_tz", "datetime_object", "date", "string"}),
    "timestamptz": frozenset({"datetime", "datetime_tz", "datetime_object", "date", "string"}),
    "uuid": frozenset({"string", "uuid"}),
}


def _build_copy_array(series: pd.Series, kind: str, session: CopySession) -> pa.Array:  # noqa: PLR0911
    """Arrow array of one column whose CSV text PostgreSQL parses into the executemany value.

    executemany semantics (psycopg 3 + SQLAlchemy bind casts) that the conversion reproduces:

    - NaN/NaT/None/pd.NA are NULL in every column (``align_partition_to_table`` masks them);
    - strings go to the type input function of the column in both paths (passthrough);
    - floats into integer columns round half to even (float8 -> int cast), into numeric they
      keep 15 significant digits (``float8_numeric`` uses ``%.15g``), into real they round to
      the nearest float4 and overflow/underflow fail;
    - datetimes are floored to microseconds; naive values into timestamptz and dates use the
      session time zone on the server; aware values into timestamp/date are converted to the
      session time zone, into timestamptz they keep their instant.
    """
    source = source_kind(series)
    if source not in _ACCEPTED_SOURCES[kind]:
        raise _CopyConversionError(f"{source} values into a {kind} column")
    mask = series.isna().to_numpy()
    if source == "datetime_object":
        series, source = _object_datetimes(series)
    if source == "string":
        return _string_array(series)
    if kind == "int":
        return _int_array(series, source, mask)
    if kind in ("float8", "float4"):
        return _float_array(series, source, mask, kind)
    if kind == "numeric":
        return _numeric_array(series, source, mask)
    if kind == "bool":
        return _plain_array(series, pa.bool_())
    if kind == "text":
        return _plain_array(series, None)
    if kind == "uuid":
        return _python_text_array(series, mask, str)
    return _temporal_array(series, source, mask, kind, session)


def _arrow(series: pd.Series) -> pa.Array:
    array = pa.array(series, from_pandas=True)
    if isinstance(array, pa.ChunkedArray):
        array = array.combine_chunks()
    return array


def _string_array(series: pd.Series) -> pa.Array:
    if isinstance(series.dtype, (pd.StringDtype, pd.ArrowDtype)):
        return _arrow(series)
    values = series.to_numpy(dtype=object, na_value=None)
    return pa.array(values, type=pa.string())


def _plain_array(series: pd.Series, arrow_type: pa.DataType | None) -> pa.Array:
    """Integers, booleans: Arrow writes them as PostgreSQL integer/boolean input text."""
    if series.dtype == object:
        values = series.to_numpy(dtype=object, na_value=None)
        return pa.array(values, type=arrow_type)
    array = _arrow(series)
    if arrow_type is not None and array.type != arrow_type:
        raise _CopyConversionError(f"unexpected Arrow type {array.type}")
    return array


def _python_text_array(series: pd.Series, mask: np.ndarray, render) -> pa.Array:
    values = series.to_numpy(dtype=object, na_value=None)
    return pa.array(
        [None if is_null else render(value) for value, is_null in zip(values, mask, strict=True)],
        type=pa.string(),
    )


def _float64_values(series: pd.Series) -> np.ndarray:
    # float32 widens exactly, as numpy float32 -> Python float in executemany.
    return series.to_numpy(dtype="float64", na_value=np.nan)


def _int_array(series: pd.Series, source: str, mask: np.ndarray) -> pa.Array:
    if source == "int":
        array = _plain_array(series, None)
        if not pa.types.is_integer(array.type):
            raise _CopyConversionError(f"unexpected Arrow type {array.type}")
        return array
    # float -> integer column: the float8 -> int cast rounds half to even, as np.rint.
    values = _float64_values(series)
    valid = values[~mask]
    if not np.isfinite(valid).all():
        raise _CopyConversionError("non-finite floats into an integer column")
    rounded = np.rint(values)
    if (np.abs(rounded[~mask]) >= 2.0**63).any():
        raise _CopyConversionError("floats outside bigint into an integer column")
    integers = np.where(mask, 0, rounded).astype(np.int64)
    return pa.array(integers, mask=mask if mask.any() else None)


def _float_array(series: pd.Series, source: str, mask: np.ndarray, kind: str) -> pa.Array:
    if source in ("int", "decimal_arrow"):
        # Integer and fixed-point text: float4in/float8in round the exact value to nearest, like
        # the int -> float and numeric -> float casts of executemany.
        return _plain_array(series, None)
    if source == "decimal":
        return _python_text_array(series, mask, str)
    values = _float64_values(series)
    doubles = pa.array(values, mask=mask if mask.any() else None)
    if kind == "float8":
        # Shortest round-trip text: float8in parses it back to the same double.
        return doubles
    singles = pc.cast(doubles, pa.float32(), safe=False)
    narrowed = singles.to_numpy(zero_copy_only=False).astype("float64")
    valid = ~mask
    overflow = np.isinf(narrowed[valid]) & np.isfinite(values[valid])
    underflow = (narrowed[valid] == 0) & (values[valid] != 0)
    if overflow.any() or underflow.any():
        # float8 -> float4 raises "value out of range" for these in executemany.
        raise _CopyConversionError("floats outside the real range")
    return singles


def _numeric_array(series: pd.Series, source: str, mask: np.ndarray) -> pa.Array:
    if source in ("int", "decimal_arrow"):
        return _plain_array(series, None)
    if source == "decimal":
        # Exact decimal text with the value's own scale (psycopg sends str(Decimal)).
        return _python_text_array(series, mask, str)
    return float8_numeric_text(_float64_values(series), mask)


def float8_numeric_text(values: np.ndarray, mask: np.ndarray) -> pa.Array:
    """Text of ``%.15g`` per float, as PostgreSQL ``float8_numeric`` formats a float8 parameter.

    A normal double whose shortest repr has at most 15 significant digits has the same ``%.15g``
    value (DBL_DIG round trip), so Arrow's shortest text is used for those; the rest are
    formatted per value.
    """
    valid = ~mask
    if not np.isfinite(values[valid]).all():
        raise _CopyConversionError("non-finite floats into a numeric column")
    doubles = pa.array(values, mask=mask if mask.any() else None)
    text = pc.cast(doubles, pa.string())
    mantissa = pc.replace_substring_regex(text, r"[eE].*$", "")
    digits = pc.utf8_trim(pc.replace_substring_regex(mantissa, r"[-+.]", ""), "0")
    magnitude = np.abs(values)
    low, high = _SHORTEST_REPR_SAFE_ABS
    too_long = pc.fill_null(pc.greater(pc.utf8_length(digits), _FLOAT8_NUMERIC_DIGITS), False)
    unsafe = too_long.to_numpy(zero_copy_only=False).astype(bool)
    unsafe |= (magnitude != 0) & ((magnitude < low) | (magnitude > high))
    unsafe &= valid
    if not unsafe.any():
        return text
    replacements = [f"%.{_FLOAT8_NUMERIC_DIGITS}g" % value for value in values[unsafe].tolist()]
    return pc.replace_with_mask(text, pa.array(unsafe), pa.array(replacements, type=pa.string()))


def _object_datetimes(series: pd.Series) -> tuple[pd.Series, str]:
    """Object datetimes as a datetime64 column: naive, or aware in one time zone."""
    try:
        converted = pd.to_datetime(series)
    except (ValueError, TypeError, OverflowError) as exc:
        raise _CopyConversionError(f"object datetimes: {exc}") from exc
    if isinstance(converted.dtype, pd.DatetimeTZDtype):
        return converted, "datetime_tz"
    if pd.api.types.is_datetime64_dtype(converted.dtype):
        return converted, "datetime"
    raise _CopyConversionError("mixed object datetimes")


def _temporal_array(
    series: pd.Series,
    source: str,
    mask: np.ndarray,
    kind: str,
    session: CopySession,
) -> pa.Array:
    if source == "date":
        if isinstance(series.dtype, pd.ArrowDtype):
            return _arrow(series).cast(pa.date32())
        values = series.to_numpy(dtype=object, na_value=None)
        return pa.array(values, type=pa.date32())
    suffix = None
    if source == "datetime_tz":
        if kind == "timestamptz":
            # The instant as UTC text with an explicit offset.
            series = series.dt.tz_convert("UTC").dt.tz_localize(None)
            suffix = "+00"
        else:
            # timestamptz -> timestamp/date casts use the session time zone.
            series = series.dt.tz_convert(session.zone()).dt.tz_localize(None)
    # psycopg sends whole microseconds (floor); numpy casts floor as well.
    micros = series.to_numpy().astype("datetime64[us]")
    valid = micros[~mask]
    if len(valid) and (valid.min() < _MIN_TIMESTAMP_US or valid.max() > _MAX_TIMESTAMP_US):
        raise _CopyConversionError("timestamps outside years 1-9999")
    arrow_mask = mask if mask.any() else None
    if kind == "date":
        return pa.array(micros.astype("datetime64[D]"), type=pa.date32(), mask=arrow_mask)
    array = pa.array(micros, type=pa.timestamp("us"), mask=arrow_mask)
    if suffix is None:
        return array
    return pc.binary_join_element_wise(pc.cast(array, pa.string()), suffix, "")
