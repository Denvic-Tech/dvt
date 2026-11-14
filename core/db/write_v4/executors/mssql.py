"""SQL Server (pyodbc) write_v4 executor: ``fast_executemany`` with fixed parameter declarations.

``SQLWriteExecutor`` inserts through SQLAlchemy's insertmanyvalues: statements of about 160 rows
(2 100 parameters) whose parameter types follow each row's Python values, so the server compiles
almost every statement again. This executor overrides only ``_insert_partition``: one
parameterised ``INSERT ... VALUES (?, ...)`` per partition, sent by pyodbc ``fast_executemany``
in calls of ``mssql_batch_rows`` rows with ``cursor.setinputsizes`` declaring every parameter, in
one transaction per partition. ``append`` inserts into the target, ``truncate``/``upsert`` into
the staging table of ``SQLWriteExecutor``.

Parity: each parameter is declared with the SQL type the inherited path binds for the source
values (``bigint`` for integers, ``float`` for floats, ``bit``, ``numeric``, ``datetime2(7)``,
``uniqueidentifier``, ``(n)varchar`` like SQLAlchemy for string columns), so the server converts
it to the column type exactly as before; sizes come from the column, never from the first row
(see ``mssql_param``). Anything without that guarantee goes through the inherited path:

- a column type outside ``MSSQL_TYPE_FAMILIES`` (xml, sql_variant, spatial, hierarchyid, text,
  ntext, image, binary, varbinary, money, rowversion, alias types, ...), an IDENTITY column (the
  inherited path sets ``IDENTITY_INSERT``), a target that is not a user table, a failed catalog
  lookup, an ODBC driver other than Microsoft ODBC Driver for SQL Server, a default-only insert:
  the whole write;
- a partition with a source column the conversion matrix does not cover with parity (for
  example floats into a string column, infinite floats, integers outside bigint): that partition.

Errors raised while inserting are not retried: they become ``WriteV4ExecutionError`` naming the
rows of the failing ``executemany`` call (``fast_executemany`` does not report the row), and the
partition's transaction leaves nothing behind.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import InvalidOperation
from threading import RLock

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyodbc
import sqlalchemy as sa

from core.db.write_v4.batching import estimate_row_bytes, rows_for_bytes
from core.db.write_v4.errors import WriteV4ExecutionError
from core.db.write_v4.executors.pg import source_kind
from core.db.write_v4.executors.sql import SQLWriteExecutor
from core.db.write_v4.models import WriteRequest
from core.db.write_v4.normalize import ColumnAlignment, align_partition_to_table

logger = logging.getLogger(__name__)

# Column families by ``sys.types`` name (alias types keep their own name and are excluded).
MSSQL_TYPE_FAMILIES: dict[str, str] = {
    "bit": "bit",
    **dict.fromkeys(("tinyint", "smallint", "int", "bigint"), "int"),
    **dict.fromkeys(("real", "float"), "float"),
    **dict.fromkeys(("decimal", "numeric"), "decimal"),
    **dict.fromkeys(("char", "varchar"), "varchar"),
    **dict.fromkeys(("nchar", "nvarchar"), "nvarchar"),
    **dict.fromkeys(("date", "datetime", "datetime2", "smalldatetime"), "datetime"),
    "datetimeoffset": "datetimeoffset",
    "time": "time",
    "uniqueidentifier": "uuid",
}
# One ``executemany`` call without ``WriteRequest.rows_per_batch``: parameter buffers or
# estimated values, whichever is larger, and at most MSSQL_MAX_BATCH_ROWS rows; more rows per call
# only cost memory (see ``mssql_batch_rows``; measurements in ``core/db/concurrency.py``).
MSSQL_AUTO_BATCH_BYTES = 8 * 1024 * 1024
MSSQL_MAX_BATCH_ROWS = 10_000
# Upper bound of the parameter array of one call, also for an explicit ``rows_per_batch``: wide
# rows get fewer rows per call.
MSSQL_BATCH_BYTES = 64 * 1024 * 1024
# String columns declared at least this long, and (n)varchar(max), are sent as max (size 0,
# streamed by the driver) like SQLAlchemy declares them, so no call allocates large buffers.
_LONG_STRING_CHARS = 2_000
# Longest non-max (n)varchar parameter.
_MAX_STRING_PARAM_CHARS = 4_000
_TIMESTAMP_SIZE = (27, 7)  # datetime2(7): microseconds are kept, the server rounds to the column
_DECIMAL_PRECISION = 38
_INT64_MIN, _INT64_MAX = -(2**63), 2**63 - 1
_MIN_DATETIME_US = np.datetime64("0001-01-01T00:00:00", "us")
_MAX_DATETIME_US = np.datetime64("9999-12-31T23:59:59.999999", "us")
# SQLAlchemy ``_ODBCDateTimeBindProcessor``: ``-0700`` -> ``-07:00``.
_DTO_OFFSET_RE = re.compile(r"([\+\-]\d{2})([\d\.]+)$")
_CATALOG_SQL = sa.text(
    """
    SELECT o.type AS object_type,
           c.name AS column_name,
           t.name AS type_name,
           c.max_length AS max_length,
           c.precision AS precision,
           c.scale AS scale,
           c.is_identity AS is_identity
    FROM sys.objects o
    JOIN sys.columns c ON c.object_id = o.object_id
    JOIN sys.types t ON t.user_type_id = c.user_type_id
    WHERE o.object_id = OBJECT_ID(:relation)
    """
)


class _ConversionError(Exception):
    """A partition column cannot be converted with parity; use the inherited path."""


@dataclass(frozen=True)
class MssqlColumn:
    """A bulk-capable column: family, ``sys.types`` name and character length (None: max)."""

    family: str
    type_name: str
    length: int | None = None


@dataclass(frozen=True)
class MssqlTarget:
    """Bulk eligibility of one table: ``columns`` maps bulk-capable columns to their spec."""

    columns: dict[str, MssqlColumn]
    type_names: dict[str, str]
    reason: str | None = None

    def unsupported_columns(self, column_names: list[str]) -> list[str]:
        return [name for name in column_names if name not in self.columns]


def build_mssql_target(rows: list[dict[str, object]]) -> MssqlTarget:
    """``MssqlTarget`` from the rows of ``_CATALOG_SQL`` (one row per column)."""
    if not rows:
        return MssqlTarget({}, {}, reason="relation not found in sys.objects")
    type_names = {str(row["column_name"]): str(row["type_name"]) for row in rows}
    object_type = str(rows[0]["object_type"]).strip()
    if object_type != "U":
        return MssqlTarget({}, type_names, reason=f"object type {object_type!r} is not a table")
    columns: dict[str, MssqlColumn] = {}
    for row in rows:
        name = str(row["column_name"])
        type_name = type_names[name]
        family = MSSQL_TYPE_FAMILIES.get(type_name)
        if family is None:
            continue
        if row["is_identity"]:
            # The inherited INSERT runs SET IDENTITY_INSERT for an explicit identity value.
            type_names[name] = f"{type_name} IDENTITY"
            continue
        columns[name] = MssqlColumn(family, type_name, _char_length(type_name, row["max_length"]))
    return MssqlTarget(columns, type_names)


def _char_length(type_name: str, max_length: object) -> int | None:
    if MSSQL_TYPE_FAMILIES[type_name] not in ("varchar", "nvarchar"):
        return None
    size = int(max_length)
    if size == -1:
        return None
    return size // 2 if type_name in ("nchar", "nvarchar") else size


def mssql_batch_rows(
    rows_per_batch: int | None, total_rows: int, row_bytes: int, data_bytes: int = 0
) -> int:
    """Rows per ``executemany`` call with ``row_bytes`` of parameter buffers per row:
    ``rows_per_batch``, or about ``MSSQL_AUTO_BATCH_BYTES`` at the larger of ``row_bytes`` and
    ``data_bytes`` (estimated value bytes per row, which also counts strings sent as max) and at
    most ``MSSQL_MAX_BATCH_ROWS``; at most ``MSSQL_BATCH_BYTES`` of buffers and at most the
    partition."""
    cap = rows_for_bytes(MSSQL_BATCH_BYTES, row_bytes, max_rows=total_rows)
    rows = rows_per_batch or rows_for_bytes(
        MSSQL_AUTO_BATCH_BYTES,
        max(row_bytes, data_bytes),
        max_rows=min(total_rows, MSSQL_MAX_BATCH_ROWS),
    )
    return max(1, min(rows, cap))


@dataclass
class MssqlParam:
    """Values of one parameter and its ``setinputsizes`` declaration."""

    values: list
    sql_type: int
    size: int = 0
    digits: int = 0

    @property
    def input_size(self) -> tuple[int, int, int]:
        return (self.sql_type, self.size, self.digits)

    @property
    def buffer_bytes(self) -> int:
        """Approximate bytes per row in the parameter array (indicator included)."""
        if self.sql_type in (pyodbc.SQL_WVARCHAR, pyodbc.SQL_VARCHAR):
            return 8 + 2 * (self.size + 1) if self.size else 16
        return 8 + 24


class MssqlWriteExecutor(SQLWriteExecutor):
    def __init__(self, engine: sa.Engine, dialect) -> None:
        super().__init__(engine, dialect)
        self._lock = RLock()
        self._targets: dict[str, MssqlTarget] = {}
        self._disabled_reason: str | None = None
        self._warned: set[str] = set()

    def _insert_partition(self, table: sa.Table, pdf: pd.DataFrame, request: WriteRequest) -> int:
        if self._disabled_reason is not None:
            return super()._insert_partition(table, pdf, request)
        alignment = align_partition_to_table(pdf, table, request, cast_to_object=False)
        if alignment.row_count == 0:
            return 0
        # Default-only rows have no columns to insert: the inherited INSERT ... DEFAULT VALUES.
        target = None if alignment.default_only_insert else self._usable_target(table, alignment)
        if target is not None:
            try:
                params = build_mssql_params(
                    alignment.normalized, alignment.insert_column_names, target.columns
                )
            except _ConversionError as exc:
                self._warn_once(
                    f"conversion:{table.fullname}:{exc}",
                    f"write_v4 MSSQL fast_executemany: a partition of {table.fullname} goes "
                    f"through the SQLAlchemy INSERT path: {exc}",
                )
            else:
                return self._fast_insert(table, alignment, params, request)
        return super()._insert_partition(table, pdf, request)

    def _usable_target(self, table: sa.Table, alignment: ColumnAlignment) -> MssqlTarget | None:
        """The target when the table and every inserted column allow the bulk path, else None."""
        target = self._target(table)
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
            f"write_v4 MSSQL fast_executemany is not used for {table.fullname}: {reason}; rows "
            "go through the SQLAlchemy INSERT path",
        )
        return None

    def _target(self, table: sa.Table) -> MssqlTarget | None:
        key = table.fullname
        with self._lock:
            if key in self._targets:
                return self._targets[key]
            relation = self.dialect.full_table_name(table.name, table.schema)
            try:
                with self.engine.connect() as conn:
                    driver = str(
                        conn.connection.driver_connection.getinfo(pyodbc.SQL_DRIVER_NAME) or ""
                    )
                    rows = [
                        dict(row._mapping)
                        for row in conn.execute(_CATALOG_SQL, {"relation": relation})
                    ]
            except (sa.exc.DBAPIError, pyodbc.Error) as exc:
                self._disable(f"catalog lookup failed: {getattr(exc, 'orig', None) or exc}")
                return None
            if "msodbcsql" not in driver.lower():
                # Parameter arrays and declarations were verified with Microsoft's driver only.
                self._disable(f"ODBC driver {driver!r} is not Microsoft ODBC Driver for SQL Server")
                return None
            target = build_mssql_target(rows)
            self._targets[key] = target
            return target

    def _disable(self, reason: str) -> None:
        self._disabled_reason = reason
        self._warn_once(
            "disabled",
            f"write_v4 MSSQL fast_executemany is unavailable, the write uses the SQLAlchemy "
            f"INSERT path: {reason}",
        )

    def _fast_insert(
        self,
        table: sa.Table,
        alignment: ColumnAlignment,
        params: list[MssqlParam],
        request: WriteRequest,
    ) -> int:
        total_rows = alignment.row_count
        row_bytes = sum(param.buffer_bytes for param in params)
        data_bytes = 0 if request.rows_per_batch else estimate_row_bytes(alignment.normalized)
        batch_rows = mssql_batch_rows(request.rows_per_batch, total_rows, row_bytes, data_bytes)
        statement = self._insert_statement(table, alignment.insert_column_names)
        input_sizes = [param.input_size for param in params]
        with self.engine.begin() as conn:
            cursor = conn.connection.driver_connection.cursor()
            cursor.fast_executemany = True
            try:
                for start in range(0, total_rows, batch_rows):
                    stop = min(start + batch_rows, total_rows)
                    rows = list(zip(*(param.values[start:stop] for param in params), strict=True))
                    try:
                        self._execute_batch(cursor, statement, input_sizes, rows)
                    except pyodbc.Error as exc:
                        raise mssql_insert_error(exc, table.fullname, start, stop) from exc
            finally:
                cursor.close()
        return total_rows

    @staticmethod
    def _execute_batch(cursor, statement: str, input_sizes: list, rows: list[tuple]) -> None:
        cursor.setinputsizes(input_sizes)
        cursor.executemany(statement, rows)

    def _insert_statement(self, table: sa.Table, columns: list[str]) -> str:
        preparer = self.engine.dialect.identifier_preparer
        names = ", ".join(preparer.quote(name) for name in columns)
        placeholders = ", ".join(["?"] * len(columns))
        return f"INSERT INTO {preparer.format_table(table)} ({names}) VALUES ({placeholders})"

    def _warn_once(self, key: str, message: str) -> None:
        with self._lock:
            if key in self._warned:
                return
            self._warned.add(key)
        logger.warning(message)


def mssql_insert_error(
    exc: pyodbc.Error, table_name: str, start: int, stop: int
) -> WriteV4ExecutionError:
    """``WriteV4ExecutionError`` for a failed ``executemany`` call of partition rows
    ``start``..``stop`` (0-based, exclusive)."""
    return WriteV4ExecutionError(
        f"MSSQL INSERT into '{table_name}' failed in partition rows {start + 1}-{stop} "
        f"(pyodbc fast_executemany does not report the failing row): {_pyodbc_message(exc)}. "
        "The partition transaction was rolled back; no rows of this partition were written."
    )


def _pyodbc_message(exc: pyodbc.Error) -> str:
    # pyodbc errors carry (SQLSTATE, message); its own client-side errors carry (message, state).
    parts = [str(arg) for arg in exc.args]
    if len(parts) >= 2 and len(parts[0]) == 5 and parts[0].isalnum():
        return parts[1]
    return parts[0] if parts else str(exc)


# ---------------------------------------------------------------------------------------------
# Partition conversion
# ---------------------------------------------------------------------------------------------

# Accepted source kinds per column family; any other combination keeps the inherited path.
# Strings go to the server's conversion in both paths. date into datetimeoffset fails in
# SQLAlchemy's bind processor, other values into bit fail in its strict boolean check.
_ACCEPTED_SOURCES: dict[str, frozenset[str]] = {
    "bit": frozenset({"bool", "int"}),
    "int": frozenset({"int", "float", "bool", "decimal", "decimal_arrow", "string"}),
    "float": frozenset({"int", "float", "decimal", "decimal_arrow", "string"}),
    "decimal": frozenset({"int", "float", "decimal", "decimal_arrow", "string"}),
    "varchar": frozenset({"string"}),
    "nvarchar": frozenset({"string"}),
    "datetime": frozenset({"datetime", "datetime_tz", "datetime_object", "date", "string"}),
    "datetimeoffset": frozenset({"datetime", "datetime_tz", "datetime_object", "string"}),
    "time": frozenset({"time", "string"}),
    "uuid": frozenset({"uuid", "string"}),
}


def build_mssql_params(
    frame: pd.DataFrame, columns: list[str], specs: dict[str, MssqlColumn]
) -> list[MssqlParam]:
    """Values and declarations of every inserted column."""
    params = []
    for name in columns:
        try:
            params.append(mssql_param(frame[name], specs[name]))
        except _ConversionError as exc:
            raise _ConversionError(f"column {name!r}: {exc}") from exc
    return params


def mssql_param(series: pd.Series, spec: MssqlColumn) -> MssqlParam:  # noqa: PLR0911
    """One parameter whose server-side conversion to the column equals the inherited path's.

    The inherited path (SQLAlchemy + pyodbc) binds Python ints as int/bigint, floats as float,
    bools as bit, Decimals as numeric, datetimes as datetime2(7) (pyodbc keeps microseconds),
    dates as datetimes at midnight, UUIDs as uniqueidentifier, strings as nvarchar (varchar for
    char/varchar columns) and ``time`` values as their ``str()``. Aware datetimes are bound by
    their wall time, except into datetimeoffset, where SQLAlchemy sends
    ``YYYY-MM-DD HH:MM:SS.ffffff +HH:MM`` text. NaN/NaT/None/NA are NULL.
    """
    source = source_kind(series)
    if source == "other" and pd.api.types.infer_dtype(series, skipna=True) == "time":
        source = "time"
    if source not in _ACCEPTED_SOURCES[spec.family]:
        raise _ConversionError(f"{source} values into a {spec.type_name} column")
    mask = series.isna().to_numpy()
    if source == "datetime_object":
        series, source = _object_datetimes(series)
    if source == "string":
        return _string_param(_object_values(series), spec)
    if spec.family == "bit":
        return MssqlParam(_bit_values(series, source, mask), pyodbc.SQL_BIT)
    if source == "int":
        return MssqlParam(_int_values(series), pyodbc.SQL_BIGINT)
    if source == "float":
        return MssqlParam(_float_values(series, mask), pyodbc.SQL_DOUBLE)
    if source == "bool":
        return MssqlParam(_bool_values(series), pyodbc.SQL_BIT)
    if source in ("decimal", "decimal_arrow"):
        return _decimal_param(_object_values(series))
    if source == "uuid":
        return MssqlParam(_object_values(series), pyodbc.SQL_GUID, 16)
    if source == "time":
        return _text_param(
            [None if value is None else str(value) for value in _object_values(series)]
        )
    if source == "date":
        dates = _object_values(series)
        return _timestamp_param(
            [None if d is None else datetime(d.year, d.month, d.day) for d in dates]
        )
    if source == "datetime_tz":
        if spec.family == "datetimeoffset":
            return _text_param(_offset_text(series, mask))
        series = series.dt.tz_localize(None)
    return _timestamp_param(_datetime_values(series, mask))


def _object_values(series: pd.Series) -> list:
    return series.to_numpy(dtype=object, na_value=None).tolist()


def _int_values(series: pd.Series) -> list:
    dtype = series.dtype
    if isinstance(dtype, np.dtype) and dtype.kind in "iu":
        values = series.to_numpy()
        if dtype == np.uint64 and len(values) and int(values.max()) > _INT64_MAX:
            raise _ConversionError("integers outside bigint")
        return values.tolist()
    values = _object_values(series)
    result = [None if value is None else int(value) for value in values]
    if any(value is not None and not _INT64_MIN <= value <= _INT64_MAX for value in result):
        raise _ConversionError("integers outside bigint")
    return result


def _float_values(series: pd.Series, mask: np.ndarray) -> list:
    # float32 widens exactly, as numpy float32 -> Python float on the inherited path.
    values = series.to_numpy(dtype="float64", na_value=np.nan)
    if np.isnan(values[~mask]).any():
        raise _ConversionError("NaN values that are not missing values")
    if not np.isfinite(values[~mask]).all():
        raise _ConversionError("infinite floats")
    result = values.tolist()
    for index in np.flatnonzero(mask).tolist():
        result[index] = None
    return result


def _bool_values(series: pd.Series) -> list:
    return [None if value is None else bool(value) for value in _object_values(series)]


def _bit_values(series: pd.Series, source: str, mask: np.ndarray) -> list:
    if source == "bool":
        return _bool_values(series)
    # SQLAlchemy's BIT bind processor accepts 0 and 1 only and raises for other integers.
    values = _int_values(series)
    if any(value not in (0, 1) for value, missing in zip(values, mask, strict=True) if not missing):
        raise _ConversionError("integers other than 0 and 1 into a bit column")
    return [None if value is None else bool(value) for value in values]


def _decimal_param(values: list) -> MssqlParam:
    """numeric(38, s) with ``s`` the largest scale of the partition: pyodbc scales every value
    up exactly (it refuses to scale down), the server rounds to the column as before."""
    scale = 0
    present = [value for value in values if value is not None]
    try:
        for value in present:
            if not value.is_finite():
                raise _ConversionError("non-finite Decimal values")
            scale = max(scale, -value.as_tuple().exponent)
        if scale > _DECIMAL_PRECISION or any(
            value and value.adjusted() >= _DECIMAL_PRECISION - scale for value in present
        ):
            raise _ConversionError("Decimal values beyond numeric(38)")
    except (AttributeError, InvalidOperation, TypeError) as exc:
        raise _ConversionError(f"Decimal values: {exc}") from exc
    return MssqlParam(values, pyodbc.SQL_NUMERIC, _DECIMAL_PRECISION, scale)


def _text_param(values: list) -> MssqlParam:
    """nvarchar sized by the longest value of the partition (max above 4000 characters)."""
    longest = _utf16_max_length(values)
    size = 0 if longest > _MAX_STRING_PARAM_CHARS else max(1, longest)
    return MssqlParam(values, pyodbc.SQL_WVARCHAR, size)


def _string_param(values: list, spec: MssqlColumn) -> MssqlParam:
    """Strings: varchar for char/varchar columns (SQLAlchemy's declaration), nvarchar otherwise.

    The declared size is the column length, so the plan stays the same across partitions; a
    longer value raises the declaration to its length (the server then truncates trailing
    blanks or raises, as before), max columns and columns of 2000+ characters are max.
    """
    if spec.family not in ("varchar", "nvarchar"):
        return _text_param(values)
    sql_type = pyodbc.SQL_VARCHAR if spec.family == "varchar" else pyodbc.SQL_WVARCHAR
    length = spec.length
    if length is None or length >= _LONG_STRING_CHARS:
        return MssqlParam(values, sql_type, 0)
    longest = _utf16_max_length(values, fits=length)
    if longest <= length:
        return MssqlParam(values, sql_type, length)
    return MssqlParam(values, sql_type, 0 if longest > _MAX_STRING_PARAM_CHARS else longest)


def _utf16_max_length(values: list, fits: int | None = None) -> int:
    """Longest value in UTF-16 code units (pyodbc's buffer unit); 0 without values.

    UTF-8 bytes bound UTF-16 units from above, so the exact count is computed only when the
    byte length exceeds ``fits``.
    """
    array = pa.array(values, type=pa.large_string())
    byte_max = pc.max(pc.binary_length(array)).as_py() or 0
    if fits is not None and byte_max <= fits:
        return byte_max
    units = pc.add(
        pc.utf8_length(array), pc.count_substring_regex(array, r"[\x{10000}-\x{10FFFF}]")
    )
    return pc.max(units).as_py() or 0


def _timestamp_param(values: list) -> MssqlParam:
    return MssqlParam(values, pyodbc.SQL_TYPE_TIMESTAMP, *_TIMESTAMP_SIZE)


def _datetime_values(series: pd.Series, mask: np.ndarray) -> list:
    # pyodbc takes whole microseconds of a Timestamp (floor); numpy casts floor as well.
    micros = series.to_numpy().astype("datetime64[us]")
    valid = micros[~mask]
    if len(valid) and (valid.min() < _MIN_DATETIME_US or valid.max() > _MAX_DATETIME_US):
        raise _ConversionError("datetimes outside years 1-9999")
    result = micros.tolist()
    for index in np.flatnonzero(mask).tolist():
        result[index] = None
    return result


def _offset_text(series: pd.Series, mask: np.ndarray) -> list:
    """SQLAlchemy's datetimeoffset text of aware values: microseconds and a ``+HH:MM`` offset."""
    values = series.astype(object).to_numpy().tolist()
    return [
        None if missing else _DTO_OFFSET_RE.sub(r"\1:\2", value.strftime("%Y-%m-%d %H:%M:%S.%f %z"))
        for value, missing in zip(values, mask.tolist(), strict=True)
    ]


def _object_datetimes(series: pd.Series) -> tuple[pd.Series, str]:
    """Object datetimes as a datetime64 column: naive, or aware in one time zone."""
    try:
        converted = pd.to_datetime(series)
    except (ValueError, TypeError, OverflowError) as exc:
        raise _ConversionError(f"object datetimes: {exc}") from exc
    if isinstance(converted.dtype, pd.DatetimeTZDtype):
        return converted, "datetime_tz"
    if pd.api.types.is_datetime64_dtype(converted.dtype):
        return converted, "datetime"
    raise _ConversionError("mixed object datetimes")
