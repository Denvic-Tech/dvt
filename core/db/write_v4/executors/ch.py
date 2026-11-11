from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal, localcontext
from threading import Lock
from uuid import uuid4

import dask.dataframe as dd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import sqlalchemy as sa
from clickhouse_connect.driver import Client
from clickhouse_connect.driver.binding import quote_identifier

from core.db.connect import build_clickhouse_client_kwargs, create_clickhouse_client
from core.db.write_v4.dask import process_partitions_bounded
from core.db.write_v4.errors import WriteV4ExecutionError
from core.db.write_v4.executors.base import WriteExecutor
from core.db.write_v4.models import WritePlan, WriteRequest, WriteResult
from core.db.write_v4.normalize import ColumnAlignment, align_partition_to_table

_DATETIME64_SCALE_RE = re.compile(r"datetime64\((\d+)")
_DECIMAL_RE = re.compile(r"decimal\((\d+),(\d+)\)$")
_DECIMAL_SIZE_RE = re.compile(r"decimal(32|64|128|256)\((\d+)\)$")
_DECIMAL_SIZE_PRECISION = {"32": 9, "64": 18, "128": 38, "256": 76}
# numpy units by DateTime64 scale; another scale uses the next finer unit and integer division.
_NUMPY_TIME_UNITS = ((0, "s"), (3, "ms"), (6, "us"), (9, "ns"))
# Base types (wrappers stripped, lower case) written through ``insert_arrow``. A write with any
# other column type (Array, Map, Tuple, UUID, Enum, IPv4, FixedString, Int128, ...) uses the
# Native ``client.insert`` path, which supports every type clickhouse_connect can serialise.
_ARROW_SCALAR_TYPES: dict[str, pa.DataType] = {
    "int8": pa.int8(),
    "int16": pa.int16(),
    "int32": pa.int32(),
    "int64": pa.int64(),
    "uint8": pa.uint8(),
    "uint16": pa.uint16(),
    "uint32": pa.uint32(),
    "uint64": pa.uint64(),
    "float32": pa.float32(),
    "float64": pa.float64(),
    "bool": pa.bool_(),
    "boolean": pa.bool_(),
    "string": pa.string(),
    "date": pa.date32(),
    "date32": pa.date32(),
}
_ARROW_ERRORS = (pa.ArrowException, TypeError, ValueError, ArithmeticError)


class _ClickHouseClientPool:
    def __init__(self, client_kwargs: dict[str, object], max_clients: int) -> None:
        self._client_kwargs = client_kwargs
        self._max_clients = max(1, max_clients)
        self._pool: list[Client] = []
        self._lock = Lock()

    def _create_client(self) -> Client:
        return create_clickhouse_client({**self._client_kwargs, "compress": True})

    @contextmanager
    def acquire(self):
        client = None
        with self._lock:
            if self._pool:
                client = self._pool.pop()
        if client is None:
            client = self._create_client()
        try:
            yield client
        finally:
            with self._lock:
                if len(self._pool) < self._max_clients:
                    self._pool.append(client)
                else:
                    client.close()

    def close_all(self) -> None:
        with self._lock:
            while self._pool:
                self._pool.pop().close()


class ClickHouseWriteExecutor(WriteExecutor):
    def execute(self, ddf: dd.DataFrame, request: WriteRequest, plan: WritePlan) -> WriteResult:
        table = self._reflect_table(request.target.table_name, request.target.schema_name)
        client_kwargs = build_clickhouse_client_kwargs(self.engine)
        pool = _ClickHouseClientPool(client_kwargs, request.write_workers)
        request_alignment = self._normalize_partition(
            ddf._meta,
            table,
            request,
            include_default_only_diagnostic=False,
        )
        diagnostics = request_alignment.diagnostics
        copy_column_names = request_alignment.insert_column_names

        try:
            if plan.mode == "append":
                written = process_partitions_bounded(
                    ddf,
                    lambda pdf: self._insert_partition(
                        pool,
                        table,
                        pdf,
                        request,
                        use_async_insert=request.async_insert,
                    ),
                    max_workers=request.write_workers,
                )
                return WriteResult(
                    mode=request.mode,
                    target_name=table.fullname,
                    rows_written=written,
                    diagnostics=diagnostics,
                )

            staging_table = self._create_staging_table(table)
            execution_error: Exception | None = None
            try:
                staged_rows = process_partitions_bounded(
                    ddf,
                    lambda pdf: self._insert_partition(
                        pool,
                        staging_table,
                        pdf,
                        request,
                        use_async_insert=False,
                    ),
                    max_workers=request.write_workers,
                )

                if plan.mode == "truncate":
                    with self.engine.begin() as conn:
                        conn.execute(
                            sa.text(
                                f"TRUNCATE TABLE {self.dialect.full_table_name(table.name, table.schema)}"
                            )
                        )
                else:
                    key_column = plan.upsert_key or ""
                    delete_sql = self._delete_using_staging_sql(table, staging_table, key_column)
                    with self.engine.begin() as conn:
                        conn.execute(sa.text(delete_sql))

                if copy_column_names:
                    self._copy_table(staging_table, table, copy_column_names)
                elif staged_rows:
                    self._insert_default_only_rows(table, staged_rows, request.chunksize)
                return WriteResult(
                    mode=request.mode,
                    target_name=table.fullname,
                    rows_written=staged_rows,
                    staging_rows=staged_rows,
                    diagnostics=diagnostics,
                )
            except Exception as exc:
                execution_error = exc
                raise
            finally:
                try:
                    self._drop_table(staging_table)
                except Exception:
                    if execution_error is None:
                        raise
        finally:
            pool.close_all()

    def _reflect_table(self, table_name: str, schema_name: str | None) -> sa.Table:
        metadata = sa.MetaData()
        return sa.Table(table_name, metadata, schema=schema_name, autoload_with=self.engine)

    def _create_staging_table(self, table: sa.Table) -> sa.Table:
        staging_name = f"{table.name}_stg_{uuid4().hex[:8]}"
        stage_full = self.dialect.full_table_name(staging_name, table.schema)
        source_full = self.dialect.full_table_name(table.name, table.schema)
        with self.engine.begin() as conn:
            conn.execute(sa.text(f"DROP TABLE IF EXISTS {stage_full}"))
            conn.execute(sa.text(f"CREATE TABLE {stage_full} AS {source_full}"))

        return self._reflect_table(staging_name, table.schema)

    def _insert_partition(
        self,
        pool: _ClickHouseClientPool,
        table: sa.Table,
        pdf: pd.DataFrame,
        request: WriteRequest,
        *,
        use_async_insert: bool,
    ) -> int:
        alignment = self._normalize_partition(pdf, table, request)
        if alignment.row_count == 0:
            return 0

        if alignment.default_only_insert:
            return self._insert_default_only_rows(table, alignment.row_count, request.chunksize)

        column_order = alignment.insert_column_names
        column_meta = self._build_column_meta(table, column_order)
        use_arrow = all(column_meta[name]["arrow_type"] is not None for name in column_order)
        total_rows = alignment.row_count
        chunk_rows = request.chunksize or total_rows
        settings = {
            "input_format_null_as_default": 1,
        }
        if use_async_insert:
            settings["async_insert"] = 1
            settings["wait_for_async_insert"] = 1

        for start in range(0, total_rows, chunk_rows):
            chunk = alignment.normalized.iloc[start: start + chunk_rows]
            if use_arrow:
                arrow_table = self._build_arrow_table(chunk, column_order, column_meta)
                with pool.acquire() as client:
                    client.insert_arrow(
                        self._quoted_table_name(table), arrow_table, settings=settings
                    )
                continue
            column_data = self._prepare_column_data(chunk, column_order, column_meta)
            with pool.acquire() as client:
                client.insert(
                    table=table.name,
                    data=column_data,
                    column_names=column_order,
                    column_type_names=[column_meta[name]["type_name"] for name in column_order],
                    column_oriented=True,
                    database=table.schema,
                    settings=settings,
                )
        return total_rows

    @staticmethod
    def _quoted_table_name(table: sa.Table) -> str:
        # insert_arrow does not quote the table name itself (client.insert does).
        name = quote_identifier(table.name)
        return f"{quote_identifier(table.schema)}.{name}" if table.schema else name

    def _normalize_partition(
        self,
        pdf: pd.DataFrame,
        table: sa.Table,
        request: WriteRequest,
        *,
        include_default_only_diagnostic: bool = True,
    ) -> ColumnAlignment:
        # Typed columns: ``_prepare_column_data`` converts them per column without ``object``.
        return align_partition_to_table(
            pdf,
            table,
            request,
            include_default_only_diagnostic=include_default_only_diagnostic,
            cast_to_object=False,
        )

    def _build_column_meta(
        self,
        table: sa.Table,
        column_order: list[str] | None = None,
    ) -> dict[str, dict[str, object]]:
        meta: dict[str, dict[str, object]] = {}
        allowed_columns = set(column_order) if column_order is not None else None
        for column in table.columns:
            if allowed_columns is not None and column.name not in allowed_columns:
                continue
            raw_type = str(column.type).strip()
            base_type = self._strip_type_wrappers(raw_type)
            type_name = self._build_insert_type_name(raw_type, column.nullable)
            meta[column.name] = {
                "type_name": type_name,
                "base_type": base_type,
                "kind": self._column_kind(base_type),
                "arrow_type": self._arrow_type(base_type),
            }
        return meta

    @staticmethod
    def _arrow_type(base_type: str) -> pa.DataType | None:
        """Arrow type of an ``insert_arrow`` column; ``None`` when the Native path is needed."""
        normalized = base_type.strip().lower().replace(" ", "")
        if normalized in _ARROW_SCALAR_TYPES:
            return _ARROW_SCALAR_TYPES[normalized]
        if normalized == "datetime" or normalized.startswith("datetime("):
            return pa.timestamp("s", tz="UTC")
        match = _DATETIME64_SCALE_RE.match(normalized)
        if match:
            scale = int(match.group(1))
            unit = next(unit for unit_scale, unit in _NUMPY_TIME_UNITS if unit_scale >= scale)
            return pa.timestamp(unit, tz="UTC")
        match = _DECIMAL_RE.match(normalized)
        if match:
            precision, scale = int(match.group(1)), int(match.group(2))
        else:
            match = _DECIMAL_SIZE_RE.match(normalized)
            if not match:
                return None
            precision, scale = _DECIMAL_SIZE_PRECISION[match.group(1)], int(match.group(2))
        if precision > 38:
            return pa.decimal256(precision, scale)
        return pa.decimal128(precision, scale)

    @classmethod
    def _column_kind(cls, base_type: str) -> str:
        """``datetime`` (DateTime/DateTime64), ``date`` (Date/Date32), ``string`` or ``value``."""
        normalized = base_type.strip().lower().replace(" ", "")
        if normalized.startswith("datetime"):
            return "datetime"
        if normalized in ("date", "date32"):
            return "date"
        if cls._is_string_like(base_type):
            return "string"
        return "value"

    @staticmethod
    def _unwrap_outer_wrapper(type_name: str, wrapper: str) -> str | None:
        normalized = type_name.strip()
        prefix = f"{wrapper}("
        if normalized.lower().startswith(prefix.lower()) and normalized.endswith(")"):
            return normalized[len(prefix):-1].strip()
        return None

    @classmethod
    def _strip_type_wrappers(cls, type_name: str) -> str:
        normalized = type_name.strip()
        while True:
            next_value = cls._unwrap_outer_wrapper(normalized, "Nullable")
            if next_value is not None:
                normalized = next_value
                continue
            next_value = cls._unwrap_outer_wrapper(normalized, "LowCardinality")
            if next_value is not None:
                normalized = next_value
                continue
            return normalized

    @staticmethod
    def _declares_nullable(type_name: str) -> bool:
        return "nullable(" in type_name.lower().replace(" ", "")

    @classmethod
    def _build_insert_type_name(cls, raw_type: str, nullable: bool) -> str:
        normalized = raw_type.strip()
        if cls._declares_nullable(normalized):
            return normalized
        if not nullable:
            return normalized
        low_cardinality_inner = cls._unwrap_outer_wrapper(normalized, "LowCardinality")
        if low_cardinality_inner is not None:
            return f"LowCardinality(Nullable({low_cardinality_inner}))"
        return f"Nullable({normalized})"

    @staticmethod
    def _is_missing(value: object) -> bool:
        if value is None:
            return True
        try:
            return bool(pd.isna(value))
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _is_string_like(base_type: str) -> bool:
        normalized = base_type.strip().lower().replace(" ", "")
        if normalized.startswith("lowcardinality(") and normalized.endswith(")"):
            normalized = normalized[len("lowcardinality("):-1]
        return normalized == "string" or normalized.startswith("fixedstring(")

    def _prepare_column_data(
        self,
        pdf: pd.DataFrame,
        column_order: list[str],
        column_meta: dict[str, dict[str, object]],
    ) -> list[list]:
        """Column lists of Python values for ``client.insert``; ``None`` marks a missing value.

        Every typed column is converted by one vectorised pass. clickhouse_connect writes
        ``int`` values of DateTime/DateTime64/Date columns as raw ticks/days, so datetime64
        columns go as epoch integers instead of ``datetime`` objects. Object columns keep the
        per-value datetime/string normalisation.
        """
        data: list[list] = []
        for column in column_order:
            series = pdf[column]
            meta = column_meta[column]
            kind = meta["kind"]
            if kind == "datetime":
                data.append(self._datetime_column(series, str(meta["base_type"])))
            elif kind == "date":
                data.append(self._date_column(series))
            elif kind == "string":
                data.append(self._string_column(series))
            else:
                data.append(self._python_values(series))
        return data

    @staticmethod
    def _python_values(series: pd.Series) -> list:
        """Python scalars with ``None`` for missing values (numpy ``tolist``, no per-value code)."""
        dtype = series.dtype
        if isinstance(dtype, np.dtype) and dtype.kind in "biuf" and not series.hasnans:
            return series.to_numpy().tolist()
        return series.to_numpy(dtype=object, na_value=None).tolist()

    def _datetime_column(self, series: pd.Series, base_type: str) -> list:
        if not pd.api.types.is_datetime64_any_dtype(series.dtype):
            return [self._normalize_datetime_value(value, base_type) for value in series.tolist()]
        unit, step = self._datetime_unit(base_type)
        values, mask = self._utc_datetime64(series, unit, step)
        return self._integers_with_nulls(values.view("int64") // step, mask)

    def _date_column(self, series: pd.Series) -> list:
        if not pd.api.types.is_datetime64_any_dtype(series.dtype):
            return self._python_values(series)
        values, mask = self._utc_datetime64(series, "D")
        return self._integers_with_nulls(values.view("int64"), mask)

    @staticmethod
    def _datetime_unit(base_type: str) -> tuple[str, int]:
        """numpy unit of a DateTime/DateTime64 type and the number of units in one tick."""
        match = _DATETIME64_SCALE_RE.match(base_type.strip().lower().replace(" ", ""))
        scale = int(match.group(1)) if match else 0
        unit_scale, unit = next(item for item in _NUMPY_TIME_UNITS if item[0] >= scale)
        return unit, 10 ** (unit_scale - scale)

    @staticmethod
    def _utc_datetime64(
        series: pd.Series, unit: str, step: int = 1
    ) -> tuple[np.ndarray, np.ndarray]:
        """Naive UTC ``datetime64[unit]`` values floored to ``step`` units and the NaT mask.

        Naive values are taken as UTC and aware values are converted to UTC, as the per-value
        ``_normalize_datetime_value`` does.
        """
        if series.dt.tz is not None:
            series = series.dt.tz_convert(None)
        values = series.to_numpy().astype(f"datetime64[{unit}]")
        if step != 1:
            values = (values.view("int64") // step * step).view(f"datetime64[{unit}]")
        return values, series.isna().to_numpy()

    @staticmethod
    def _integers_with_nulls(ticks: np.ndarray, mask: np.ndarray) -> list:
        # clickhouse_connect writes a Date/DateTime column whose first value is an int as raw
        # days/ticks, without per-value datetime conversion.
        values = ticks.tolist()
        for index in np.flatnonzero(mask).tolist():
            values[index] = None
        return values

    def _string_column(self, series: pd.Series) -> list:
        values = series.to_numpy(dtype=object, na_value=None)
        if pd.api.types.infer_dtype(values, skipna=True) in ("string", "bytes", "empty"):
            return values.tolist()
        return [self._normalize_string_value(value) for value in values.tolist()]

    def _build_arrow_table(
        self,
        pdf: pd.DataFrame,
        column_order: list[str],
        column_meta: dict[str, dict[str, object]],
    ) -> pa.Table:
        """Arrow table with the exact Arrow type of every target column for ``insert_arrow``.

        Values keep the semantics of the Native path: datetimes in UTC floored to the column
        precision, Decimal from ``Decimal(str(value))`` truncated to the scale, float to integer
        by truncation, strings via ``_normalize_string_value``. Missing values become Arrow
        nulls (``input_format_null_as_default`` applies to non-Nullable columns).
        """
        arrays = []
        for column in column_order:
            meta = column_meta[column]
            try:
                arrays.append(self._arrow_column(pdf[column], meta))
            except _ARROW_ERRORS as exc:
                raise WriteV4ExecutionError(
                    f"Column {column!r} cannot be converted to ClickHouse type "
                    f"{meta['type_name']}: {exc}"
                ) from exc
        return pa.Table.from_arrays(arrays, names=column_order)

    def _arrow_column(self, series: pd.Series, meta: dict[str, object]) -> pa.Array:
        target = meta["arrow_type"]
        base_type = str(meta["base_type"]).strip().lower()
        if pa.types.is_timestamp(target):
            array = self._arrow_datetime(series, str(meta["base_type"]), target)
            if not base_type.startswith("datetime64"):
                # DateTime is UInt32 seconds; ClickHouse would wrap Arrow values outside it.
                self._check_range(array.view(pa.int64()), 2**32 - 1, "DateTime")
            return array
        if pa.types.is_date32(target):
            array = self._arrow_date(series)
            if base_type == "date":
                # Date is UInt16 days since 1970-01-01; ClickHouse would clamp values outside.
                self._check_range(array.view(pa.int32()), 2**16 - 1, "Date")
            return array
        if pa.types.is_string(target):
            return self._arrow_string(series)
        if pa.types.is_decimal(target):
            return self._arrow_decimal(series, target)
        return self._arrow_number(series, target)

    @staticmethod
    def _check_range(integers: pa.Array, high: int, type_name: str) -> None:
        bounds = pc.min_max(integers).as_py()
        if bounds["min"] is not None and (bounds["min"] < 0 or bounds["max"] > high):
            raise ValueError(f"value out of range for ClickHouse {type_name}")

    def _arrow_datetime(self, series: pd.Series, base_type: str, target: pa.DataType) -> pa.Array:
        if not pd.api.types.is_datetime64_any_dtype(series.dtype):
            normalized = [self._normalize_datetime_value(value, base_type) for value in series]
            series = pd.Series(pd.to_datetime(normalized, utc=True))
        unit, step = self._datetime_unit(base_type)
        values, mask = self._utc_datetime64(series, unit, step)
        return pa.array(values, type=target, mask=mask if mask.any() else None)

    def _arrow_date(self, series: pd.Series) -> pa.Array:
        if pd.api.types.is_datetime64_any_dtype(series.dtype):
            values, mask = self._utc_datetime64(series, "D")
            return pa.array(values, type=pa.date32(), mask=mask if mask.any() else None)
        values = series.to_numpy(dtype=object, na_value=None).tolist()
        return pa.array([self._to_date(value) for value in values], type=pa.date32())

    @staticmethod
    def _to_date(value: object) -> date | None:
        if value is None or (isinstance(value, date) and not isinstance(value, datetime)):
            return value
        if isinstance(value, datetime):
            return (value.astimezone(UTC) if value.tzinfo is not None else value).date()
        raise TypeError(f"expected a date or datetime, got {type(value).__name__}")

    def _arrow_string(self, series: pd.Series) -> pa.Array:
        if isinstance(series.dtype, pd.StringDtype):
            return pa.Array.from_pandas(series)
        values = series.to_numpy(dtype=object, na_value=None)
        inferred = pd.api.types.infer_dtype(values, skipna=True)
        if inferred in ("string", "empty"):
            return pa.array(values, type=pa.string())
        if inferred != "bytes":
            values = [self._normalize_string_value(value) for value in values.tolist()]
            if not any(isinstance(value, (bytes, bytearray, memoryview)) for value in values):
                return pa.array(values, type=pa.string())
        # Raw bytes go unchanged as Arrow binary; str values are UTF-8 encoded like the driver.
        return pa.array(
            [value.encode() if isinstance(value, str) else value for value in values],
            type=pa.binary(),
        )

    @staticmethod
    def _arrow_decimal(series: pd.Series, target: pa.DataType) -> pa.Array:
        """Decimal values as ``int(Decimal(str(value)) * 10**scale)`` (the driver semantics).

        A numeric column whose every value has at most ``scale`` decimals in its shortest repr
        (checked by the float round trip) is converted without Python objects; any other value
        sends the whole column through ``Decimal(str(value))``.
        """
        precision, scale = target.precision, target.scale
        factor = 10**scale
        dtype = series.dtype
        if pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype):
            numbers = series.to_numpy(dtype="float64", na_value=np.nan)
            mask = np.isnan(numbers)
            with np.errstate(invalid="ignore"):
                units = np.rint(numbers * factor)
                exact = (np.abs(units) < 2.0**52) & (units / factor == numbers)
            if (exact | mask).all():
                units = np.where(mask, 0, units).astype(np.int64)
                if (np.abs(units) >= 10.0**precision).any():
                    raise ValueError(f"value out of range for Decimal({precision}, {scale})")
                storage = pa.decimal128(38, 0) if target.byte_width == 16 else pa.decimal256(76, 0)
                integers = pa.array(units, mask=mask if mask.any() else None)
                return integers.cast(storage).view(target)
        values = series.to_numpy(dtype=object, na_value=None).tolist()
        with localcontext() as context:
            context.prec = precision
            decimals = [
                None if value is None else Decimal(int(Decimal(str(value)) * factor)).scaleb(-scale)
                for value in values
            ]
        return pa.array(decimals, type=target)

    @staticmethod
    def _arrow_number(series: pd.Series, target: pa.DataType) -> pa.Array:
        """Integer, float and Bool columns; object values go through ``int``/``float``/``bool``."""
        if series.dtype == object:
            if pa.types.is_integer(target):
                convert = int
            elif pa.types.is_floating(target):
                convert = float
            else:
                convert = bool
            values = series.to_numpy(dtype=object, na_value=None).tolist()
            return pa.array([None if v is None else convert(v) for v in values], type=target)
        array = pa.Array.from_pandas(series)
        if pa.types.is_boolean(target) and not pa.types.is_boolean(array.type):
            return pc.not_equal(array, 0)
        if pa.types.is_integer(target) and pa.types.is_floating(array.type):
            array = pc.trunc(array)
        # Range checks for integers; float targets accept precision loss like ``float()``.
        return array.cast(target, safe=not pa.types.is_floating(target))

    def _insert_default_only_rows(self, table: sa.Table, row_count: int, chunksize: int | None) -> int:
        chunk_rows = chunksize or row_count
        target_full = self.dialect.full_table_name(table.name, table.schema)
        with self.engine.begin() as conn:
            for start in range(0, row_count, chunk_rows):
                batch_rows = min(chunk_rows, row_count - start)
                values_sql = ", ".join("()" for _ in range(batch_rows))
                conn.execute(sa.text(f"INSERT INTO {target_full} VALUES {values_sql}"))
        return row_count

    def _normalize_string_value(self, value: object) -> object:
        if self._is_missing(value):
            return None
        if isinstance(value, (str, bytes, bytearray, memoryview)):
            return value
        return str(value)

    def _normalize_datetime_value(self, value: object, base_type: str) -> object:
        if self._is_missing(value):
            return None
        try:
            ts = value if isinstance(value, pd.Timestamp) else pd.Timestamp(value)
        except Exception:
            return None
        if pd.isna(ts):
            return None
        if ts.tz is None:
            ts_utc = ts.tz_localize("UTC")
        else:
            ts_utc = ts.tz_convert("UTC")
        if self._is_datetime_seconds_type(base_type):
            ts_utc = ts_utc.floor("s")
        return ts_utc.to_pydatetime()

    @staticmethod
    def _is_datetime_seconds_type(base_type: str) -> bool:
        normalized = base_type.strip().lower().replace(" ", "")
        return normalized == "datetime" or normalized.startswith("datetime(")

    def _copy_table(
        self,
        source_table: sa.Table,
        target_table: sa.Table,
        columns: list[str] | None = None,
    ) -> None:
        if columns is None:
            columns = [column.name for column in target_table.columns if column.name in source_table.c]
        quoted_columns = ", ".join(self.dialect.quote_ident(column) for column in columns)
        target_full = self.dialect.full_table_name(target_table.name, target_table.schema)
        source_full = self.dialect.full_table_name(source_table.name, source_table.schema)
        sql = (
            f"INSERT INTO {target_full} ({quoted_columns}) "
            f"SELECT {quoted_columns} FROM {source_full}"
        )
        with self.engine.begin() as conn:
            conn.execute(sa.text(sql))

    def _delete_using_staging_sql(self, target_table: sa.Table, staging_table: sa.Table, key_column: str) -> str:
        target_full = self.dialect.full_table_name(target_table.name, target_table.schema)
        staging_full = self.dialect.full_table_name(staging_table.name, staging_table.schema)
        target_key = self.dialect.quote_ident(key_column)
        return (
            f"ALTER TABLE {target_full} DELETE "
            f"WHERE {target_key} IN ("
            f"SELECT DISTINCT {target_key} FROM {staging_full} WHERE {target_key} IS NOT NULL"
            f") OR ({target_key} IS NULL AND EXISTS ("
            f"SELECT 1 FROM {staging_full} WHERE {target_key} IS NULL"
            f")) SETTINGS mutations_sync = 1"
        )

    def _drop_table(self, table: sa.Table) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                sa.text(f"DROP TABLE IF EXISTS {self.dialect.full_table_name(table.name, table.schema)}")
            )
