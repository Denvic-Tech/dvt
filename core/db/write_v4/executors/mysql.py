"""MySQL/MariaDB (PyMySQL) write_v4 executor: one transaction per partition, raw ``executemany``.

``SQLWriteExecutor`` converts every chunk with ``astype(object)`` + ``to_dict("records")``, runs it
through SQLAlchemy bind processing and commits each chunk of rows (1000 by default). This
executor overrides only ``_insert_partition``: the partition is converted column by column into
Python values, inserted with PyMySQL ``cursor.executemany`` (``mysql_batch_rows`` rows per call;
PyMySQL folds them into multi-row ``INSERT`` statements of at most ``statement_bytes``) and
committed once. ``append`` inserts into the target, ``truncate``/``upsert`` into the staging table
of ``SQLWriteExecutor``.

PyMySQL renders every parameter as an SQL literal chosen by its Python type, so a value is stored
as the inherited path stores it when it is the same Python object: ``mysql_column_values`` builds
those objects (see there). Anything without that guarantee goes through the inherited path:

- a column whose ``information_schema`` type is outside ``MYSQL_TYPE_FAMILIES`` (json, enum, set,
  spatial, MariaDB uuid/inet, ...), a generated column, a column with an unexpected SQLAlchemy
  bind processor, a target that is not a base table, a failed catalog lookup, a default-only
  insert: the whole write;
- a partition whose values the conversion cannot reproduce (for example a non-bytes value in a
  binary column, which fails in SQLAlchemy on the inherited path): that partition.

Errors raised while inserting (server data errors, values PyMySQL cannot render) are not retried:
they become ``WriteV4ExecutionError`` and the partition's transaction is rolled back.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import RLock

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pymysql
import sqlalchemy as sa
from pandas.core.dtypes.cast import maybe_box_native

from core.db.write_v4.batching import estimate_row_bytes, rows_for_bytes
from core.db.write_v4.errors import WriteV4ExecutionError
from core.db.write_v4.executors.sql import SQLWriteExecutor
from core.db.write_v4.models import WriteRequest
from core.db.write_v4.normalize import ColumnAlignment, align_partition_to_table

logger = logging.getLogger(__name__)

# ``information_schema.COLUMNS.DATA_TYPE`` values written through the bulk path. Binary columns
# go through SQLAlchemy's ``Binary`` bind processor on the inherited path (``bytes(value)``),
# which ``_binary_values`` repeats; the other families have no bind processor.
MYSQL_TYPE_FAMILIES: dict[str, str] = {
    **dict.fromkeys(("tinyint", "smallint", "mediumint", "int", "integer", "bigint"), "int"),
    **dict.fromkeys(("float", "double", "real", "decimal", "numeric", "bit", "year"), "number"),
    **dict.fromkeys(("char", "varchar", "tinytext", "text", "mediumtext", "longtext"), "string"),
    **dict.fromkeys(("date", "datetime", "timestamp", "time"), "temporal"),
    **dict.fromkeys(
        ("binary", "varbinary", "tinyblob", "blob", "mediumblob", "longblob"), "binary"
    ),
}
# Upper bound of one multi-row INSERT built by PyMySQL ``executemany`` (its ``max_stmt_length``);
# a server ``max_allowed_packet`` below it lowers the bound. See ``mysql_statement_bytes``.
MYSQL_STATEMENT_BYTES = 4 * 1024 * 1024
# Estimated row bytes (``estimate_row_bytes``) of one ``executemany`` call without
# ``WriteRequest.rows_per_batch``: several full statements per call, since every statement costs
# one round trip and a call ends with a partial one (see ``mysql_batch_rows``; measurements in
# ``core/db/concurrency.py``). At most MYSQL_MAX_BATCH_ROWS rows: more rows per call only cost
# memory (the row tuples of a call, about 80 bytes per row on top of the values).
MYSQL_BATCH_BYTES = 16 * 1024 * 1024
MYSQL_MAX_BATCH_ROWS = 10_000
# Bytes kept below ``max_allowed_packet`` for the packet header and the statement's tail.
_PACKET_MARGIN = 1024
_CATALOG_SQL = sa.text(
    """
    SELECT t.TABLE_TYPE AS table_type,
           c.COLUMN_NAME AS column_name,
           c.DATA_TYPE AS data_type,
           c.EXTRA AS extra
    FROM information_schema.TABLES t
    JOIN information_schema.COLUMNS c
      ON c.TABLE_SCHEMA = t.TABLE_SCHEMA AND c.TABLE_NAME = t.TABLE_NAME
    WHERE t.TABLE_SCHEMA = COALESCE(:schema, DATABASE()) AND t.TABLE_NAME = :table
    """
)


class _ConversionError(Exception):
    """A partition column cannot be converted with parity; use the inherited path."""


@dataclass(frozen=True)
class MysqlTarget:
    """Bulk eligibility of one table: ``families`` maps bulk-capable columns to their family."""

    families: dict[str, str]
    type_names: dict[str, str]
    statement_bytes: int
    reason: str | None = None

    def unsupported_columns(self, column_names: list[str]) -> list[str]:
        return [name for name in column_names if name not in self.families]


def build_mysql_target(rows: list[dict[str, object]], max_allowed_packet: int) -> MysqlTarget:
    """``MysqlTarget`` from the rows of ``_CATALOG_SQL`` (one row per column)."""
    statement_bytes = mysql_statement_bytes(max_allowed_packet)
    if not rows:
        return MysqlTarget({}, {}, statement_bytes, reason="table not found in information_schema")
    type_names = {str(row["column_name"]): str(row["data_type"]).lower() for row in rows}
    table_type = str(rows[0]["table_type"])
    if table_type != "BASE TABLE":
        return MysqlTarget({}, type_names, statement_bytes, reason=f"{table_type} is not a table")
    families: dict[str, str] = {}
    for row in rows:
        name = str(row["column_name"])
        family = MYSQL_TYPE_FAMILIES.get(type_names[name])
        if family is not None and "GENERATED" not in str(row["extra"] or "").upper():
            families[name] = family
    return MysqlTarget(families, type_names, statement_bytes)


def mysql_statement_bytes(max_allowed_packet: int) -> int:
    """Largest multi-row INSERT PyMySQL may build: ``MYSQL_STATEMENT_BYTES`` capped by the
    server ``max_allowed_packet`` (a single row above it is still sent alone, as before)."""
    return max(1024, min(MYSQL_STATEMENT_BYTES, int(max_allowed_packet) - _PACKET_MARGIN))


def mysql_batch_rows(rows_per_batch: int | None, total_rows: int, row_bytes: int) -> int:
    """Rows per ``executemany`` call: ``rows_per_batch``, or about ``MYSQL_BATCH_BYTES`` at
    ``row_bytes`` per row and at most ``MYSQL_MAX_BATCH_ROWS``; at most the partition. Statements
    stay within ``statement_bytes`` either way."""
    rows = rows_per_batch or rows_for_bytes(
        MYSQL_BATCH_BYTES, row_bytes, max_rows=min(total_rows, MYSQL_MAX_BATCH_ROWS)
    )
    return max(1, min(rows, total_rows))


class MysqlWriteExecutor(SQLWriteExecutor):
    def __init__(self, engine: sa.Engine, dialect) -> None:
        super().__init__(engine, dialect)
        self._lock = RLock()
        self._targets: dict[str, MysqlTarget] = {}
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
                columns = build_mysql_columns(
                    alignment.normalized, alignment.insert_column_names, target.families
                )
            except _ConversionError as exc:
                self._warn_once(
                    f"conversion:{table.fullname}:{exc}",
                    f"write_v4 MySQL bulk insert: a partition of {table.fullname} goes through "
                    f"the SQLAlchemy INSERT path: {exc}",
                )
            else:
                return self._bulk_insert(table, target, alignment, columns, request)
        return super()._insert_partition(table, pdf, request)

    def _usable_target(self, table: sa.Table, alignment: ColumnAlignment) -> MysqlTarget | None:
        """The target when the table and every inserted column allow the bulk path, else None."""
        target = self._target(table)
        if target is None:
            return None
        columns = alignment.insert_column_names
        unsupported = target.unsupported_columns(columns)
        unsupported += [
            name
            for name in columns
            if name not in unsupported
            and target.families[name] != "binary"
            and self._has_bind_processor(table.c[name])
        ]
        if target.reason is None and not unsupported:
            return target
        reason = target.reason or ", ".join(
            f"{name} ({target.type_names.get(name, '?')})" for name in unsupported
        )
        self._warn_once(
            f"target:{table.fullname}",
            f"write_v4 MySQL bulk insert is not used for {table.fullname}: {reason}; rows go "
            "through the SQLAlchemy INSERT path",
        )
        return None

    def _has_bind_processor(self, column: sa.Column) -> bool:
        dialect = self.engine.dialect
        return column.type.dialect_impl(dialect).bind_processor(dialect) is not None

    def _target(self, table: sa.Table) -> MysqlTarget | None:
        key = table.fullname
        with self._lock:
            if key in self._targets:
                return self._targets[key]
            try:
                with self.engine.connect() as conn:
                    rows = [
                        dict(row._mapping)
                        for row in conn.execute(
                            _CATALOG_SQL, {"schema": table.schema, "table": table.name}
                        )
                    ]
                    max_allowed_packet = conn.exec_driver_sql(
                        "SELECT @@max_allowed_packet"
                    ).scalar_one()
            except sa.exc.DBAPIError as exc:
                self._disabled_reason = f"catalog lookup failed: {exc.orig or exc}"
                self._warn_once(
                    "catalog",
                    "write_v4 MySQL bulk insert is unavailable, the write uses the SQLAlchemy "
                    f"INSERT path: {self._disabled_reason}",
                )
                return None
            target = build_mysql_target(rows, int(max_allowed_packet))
            self._targets[key] = target
            return target

    def _bulk_insert(
        self,
        table: sa.Table,
        target: MysqlTarget,
        alignment: ColumnAlignment,
        columns: list[list],
        request: WriteRequest,
    ) -> int:
        total_rows = alignment.row_count
        batch_rows = mysql_batch_rows(
            request.rows_per_batch, total_rows, estimate_row_bytes(alignment.normalized)
        )
        statement = self._insert_statement(table, alignment.insert_column_names)
        with self.engine.begin() as conn:
            cursor = conn.connection.driver_connection.cursor()
            cursor.max_stmt_length = target.statement_bytes
            try:
                for start in range(0, total_rows, batch_rows):
                    stop = min(start + batch_rows, total_rows)
                    rows = list(zip(*(values[start:stop] for values in columns), strict=True))
                    self._execute_batch(cursor, statement, rows)
            except (pymysql.err.MySQLError, TypeError, ValueError) as exc:
                raise mysql_insert_error(exc, table.fullname) from exc
            finally:
                cursor.close()
        return total_rows

    @staticmethod
    def _execute_batch(cursor, statement: str, rows: list[tuple]) -> None:
        cursor.executemany(statement, rows)

    def _insert_statement(self, table: sa.Table, columns: list[str]) -> str:
        # SQLAlchemy's preparer quotes like the inherited INSERT and doubles "%" for PyMySQL.
        preparer = self.engine.dialect.identifier_preparer
        names = ", ".join(preparer.quote(name) for name in columns)
        placeholders = ", ".join(["%s"] * len(columns))
        return f"INSERT INTO {preparer.format_table(table)} ({names}) VALUES ({placeholders})"

    def _warn_once(self, key: str, message: str) -> None:
        with self._lock:
            if key in self._warned:
                return
            self._warned.add(key)
        logger.warning(message)


def mysql_insert_error(exc: Exception, table_name: str) -> WriteV4ExecutionError:
    """``WriteV4ExecutionError`` for an error raised while inserting a partition."""
    if isinstance(exc, pymysql.err.MySQLError) and len(exc.args) >= 2:
        detail = f"({exc.args[0]}) {exc.args[1]}"
    else:
        detail = f"{type(exc).__name__}: {exc}"
    return WriteV4ExecutionError(
        f"MySQL INSERT into '{table_name}' failed: {detail}. A row number in a MySQL message "
        "counts rows of the failing multi-row INSERT statement, not of the partition. The "
        "partition transaction was rolled back; with a transactional engine (InnoDB) no rows of "
        "this partition were written."
    )


# ---------------------------------------------------------------------------------------------
# Partition conversion
# ---------------------------------------------------------------------------------------------


def build_mysql_columns(
    frame: pd.DataFrame, columns: list[str], families: dict[str, str]
) -> list[list]:
    """Per-column lists of the Python values the inherited path hands to PyMySQL."""
    result = []
    for name in columns:
        values = mysql_column_values(frame[name])
        if families[name] == "binary":
            try:
                values = _binary_values(values)
            except (TypeError, ValueError) as exc:
                raise _ConversionError(f"column {name!r}: {exc}") from exc
        result.append(values)
    return result


def mysql_column_values(series: pd.Series) -> list:
    """Python values of one column whose PyMySQL literals equal the inherited path's.

    The inherited path stores ``astype(object)`` values with ``None`` where ``notna()`` is false,
    boxed by ``to_dict`` (``maybe_box_native``), and PyMySQL renders a literal per Python type.
    Plain numpy integers, booleans and floats, and string columns produce the same objects
    directly; naive ``datetime64`` columns produce ``str(Timestamp)`` text (PyMySQL quotes a
    ``Timestamp`` as ``str(value)`` too); every other dtype uses the inherited conversion.
    """
    dtype = series.dtype
    if isinstance(dtype, np.dtype):
        if dtype.kind in "biu":
            return series.to_numpy().tolist()
        if dtype.kind == "f":
            values = series.to_numpy()
            result = values.tolist()
            for index in np.flatnonzero(np.isnan(values)).tolist():
                result[index] = None
            return result
        if dtype.kind == "M":
            return timestamp_text(series)
    if isinstance(dtype, pd.StringDtype):
        return series.to_numpy(dtype=object, na_value=None).tolist()
    return inherited_values(series)


def inherited_values(series: pd.Series) -> list:
    """The inherited path's values: ``astype(object)``, ``None`` where missing, native boxing."""
    keep = series.notna().to_numpy()
    values = series.astype(object).to_numpy()
    return [
        maybe_box_native(value) if present else None
        for value, present in zip(values.tolist(), keep.tolist(), strict=True)
    ]


_NS_PER_UNIT = {"s": 1_000_000_000, "ms": 1_000_000, "us": 1_000, "ns": 1}
_UNITS_PER_SECOND = {"s": 1, "ms": 1_000, "us": 1_000_000, "ns": 1_000_000_000}
# ``np.datetime_as_string`` and ``str(Timestamp)`` agree on four-digit years only.
_MIN_TEXT_SECOND = np.datetime64("1000-01-01T00:00:00", "s")
_MAX_TEXT_SECOND = np.datetime64("9999-12-31T23:59:59", "s")


def timestamp_text(series: pd.Series) -> list:
    """``str(Timestamp)`` of every value of a naive ``datetime64`` column, ``None`` for NaT.

    ``Timestamp.__str__`` prints ``YYYY-MM-DD HH:MM:SS`` plus ``.ffffff`` when the microsecond
    part is set or ``.fffffffff`` when the nanosecond part is set.
    """
    values = series.to_numpy()
    unit = np.datetime_data(values.dtype)[0]
    if unit not in _NS_PER_UNIT:
        return inherited_values(series)
    mask = np.isnat(values)
    seconds = values.astype("datetime64[s]")
    valid = seconds[~mask]
    if len(valid) and (valid.min() < _MIN_TEXT_SECOND or valid.max() > _MAX_TEXT_SECOND):
        return inherited_values(series)
    ticks = values.view("int64")
    sub_ns = (ticks % _UNITS_PER_SECOND[unit]) * _NS_PER_UNIT[unit]
    base = np.char.replace(np.datetime_as_string(seconds, unit="s"), "T", " ")
    text = pa.array(base, type=pa.string())
    if sub_ns.any():
        nanos = pc.utf8_lpad(pa.array(sub_ns).cast(pa.string()), 9, "0")
        micros = pc.utf8_slice_codeunits(nanos, 0, 6)
        fraction = pc.if_else(
            pa.array(sub_ns % 1_000 != 0),
            pc.binary_join_element_wise(".", nanos, ""),
            pc.if_else(pa.array(sub_ns != 0), pc.binary_join_element_wise(".", micros, ""), ""),
        )
        text = pc.binary_join_element_wise(text, fraction, "")
    result = text.to_pylist()
    for index in np.flatnonzero(mask).tolist():
        result[index] = None
    return result


def _binary_values(values: list) -> list:
    # SQLAlchemy's Binary bind processor: ``pymysql.Binary(value)`` is ``bytes(value)``.
    return [None if value is None else bytes(value) for value in values]
