"""ClickHouse read_v3 executor: pooled clients and an Arrow fetch path for segment queries.

When every column of a segment has a ClickHouse type from the allow-list below, the segment is
fetched in the Arrow format and converted column by column into the dtypes and values
``Client.query_df`` produces for the same data; any other type sends the whole segment through
``query_df``. Planning and metadata queries keep using the SQL runner.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock

import pandas as pd
import pyarrow as pa
from clickhouse_connect.driver import tzutil
from clickhouse_connect.driver.client import Client
from sqlalchemy.engine import Engine

from core.db.connect import build_clickhouse_client_kwargs, create_clickhouse_client
from core.db.read_v3.dialects.base import SQLDialect
from core.db.read_v3.executors.sql import SQLReadExecutor
from core.db.read_v3.models import ReadV3Plan

logger = logging.getLogger(__name__)

_DEFAULT_CLIENT_POOL_SIZE = 4

_INTEGER_ARROW_TYPES: dict[str, pa.DataType] = {
    "int8": pa.int8(),
    "int16": pa.int16(),
    "int32": pa.int32(),
    "int64": pa.int64(),
    "uint8": pa.uint8(),
    "uint16": pa.uint16(),
    "uint32": pa.uint32(),
    "uint64": pa.uint64(),
}
_FLOAT_ARROW_TYPES: dict[str, pa.DataType] = {"float32": pa.float32(), "float64": pa.float64()}
_DECIMAL_TYPE_ARITY = {
    "decimal": 2,
    "decimal32": 1,
    "decimal64": 1,
    "decimal128": 1,
    "decimal256": 1,
}
# query_df returns pandas nullable integers of the same width for Nullable(Int*/UInt*).
_NULLABLE_INTEGER_DTYPES: dict[pa.DataType, pd.api.extensions.ExtensionDtype] = {
    pa.int8(): pd.Int8Dtype(),
    pa.int16(): pd.Int16Dtype(),
    pa.int32(): pd.Int32Dtype(),
    pa.int64(): pd.Int64Dtype(),
    pa.uint8(): pd.UInt8Dtype(),
    pa.uint16(): pd.UInt16Dtype(),
    pa.uint32(): pd.UInt32Dtype(),
    pa.uint64(): pd.UInt64Dtype(),
}
# Exceptions that mean "this Arrow result cannot be converted with query_df parity" (invalid
# UTF-8, out-of-range timestamps, an unexpected Arrow type); ArrowMemoryError is not one of them.
_ARROW_CONVERSION_ERRORS = (pa.ArrowInvalid, pa.ArrowNotImplementedError, pa.ArrowTypeError)

_WRAPPER_RE = re.compile(r"(nullable|lowcardinality)\s*\((.*)\)", re.IGNORECASE | re.DOTALL)
_TYPE_RE = re.compile(r"([a-z0-9]+)\s*(?:\((.*)\))?", re.IGNORECASE | re.DOTALL)


class _ArrowConversionError(Exception):
    """The Arrow result cannot be converted with query_df parity; re-read through query_df."""


@dataclass(frozen=True)
class _ArrowColumnSpec:
    # int | float | bool | string | date | datetime | decimal
    kind: str
    nullable: bool = False
    # Exact Arrow width for int/float columns.
    arrow_type: pa.DataType | None = None
    # Explicit DateTime/DateTime64 column timezone.
    timezone: str | None = None


def _timezone_arg(raw: str) -> str | None:
    # Reflected table types may quote the timezone twice: DateTime(''Asia/Tokyo'').
    return raw.strip().strip("'\"").strip() or None


def _parse_arrow_column_spec(type_repr: str) -> _ArrowColumnSpec | None:  # noqa: PLR0911
    """Return the Arrow conversion spec for an allow-listed ClickHouse type, else ``None``."""
    raw = (type_repr or "").strip()
    nullable = False
    while (wrapper := _WRAPPER_RE.fullmatch(raw)) is not None:
        nullable = nullable or wrapper.group(1).lower() == "nullable"
        raw = wrapper.group(2).strip()

    match = _TYPE_RE.fullmatch(raw)
    if match is None:
        return None
    name = match.group(1).lower()
    args = [] if match.group(2) is None else [arg.strip() for arg in match.group(2).split(",")]

    if name in _INTEGER_ARROW_TYPES and not args:
        return _ArrowColumnSpec("int", nullable, arrow_type=_INTEGER_ARROW_TYPES[name])
    if name in _FLOAT_ARROW_TYPES and not args:
        return _ArrowColumnSpec("float", nullable, arrow_type=_FLOAT_ARROW_TYPES[name])
    if name in {"bool", "string"} and not args:
        return _ArrowColumnSpec(name, nullable)
    if name in {"date", "date32"} and not args:
        return _ArrowColumnSpec("date", nullable)
    if name == "datetime" and len(args) <= 1:
        return _ArrowColumnSpec(
            "datetime", nullable, timezone=_timezone_arg(args[0]) if args else None
        )
    if name == "datetime64" and len(args) in {1, 2} and args[0].isdigit() and int(args[0]) <= 9:
        return _ArrowColumnSpec(
            "datetime", nullable, timezone=_timezone_arg(args[1]) if len(args) == 2 else None
        )
    if (
        name in _DECIMAL_TYPE_ARITY
        and len(args) == _DECIMAL_TYPE_ARITY[name]
        and all(arg.isdigit() for arg in args)
    ):
        return _ArrowColumnSpec("decimal", nullable)
    return None


def _segment_arrow_specs(plan: ReadV3Plan) -> dict[str, _ArrowColumnSpec] | None:
    """Specs by result column name when the whole segment can use Arrow, else ``None``."""
    specs: dict[str, _ArrowColumnSpec] = {}
    for column in plan.output_columns:
        spec = _parse_arrow_column_spec(plan.output_column_type_repr.get(column, ""))
        if spec is None:
            return None
        specs[column] = spec
        specs.setdefault(plan.output_column_sql_names.get(column, column), spec)

    # The planners select the raw key under partition_key_alias when it is not an output column.
    if plan.partition_key_name not in plan.output_columns:
        key_spec = _parse_arrow_column_spec(plan.partition_key_type_repr)
        if key_spec is None:
            return None
        specs[plan.partition_key_alias] = key_spec
    return specs


def _default_timezone_name(client: Client) -> str:
    # Mirrors QueryContext.active_tz for a column without its own timezone (no query/column tz).
    tz = client.server_tz if client.apply_server_timezone else tzutil.local_tz
    name = getattr(tz, "zone", None)
    if not name:
        raise _ArrowConversionError(f"Cannot name the client default timezone {tz!r}")
    return str(name)


def _target_timezone(spec: _ArrowColumnSpec, client: Client) -> str | None:
    name = spec.timezone or _default_timezone_name(client)
    # query_df returns naive datetimes when the active timezone is UTC.
    if name.upper() == "UTC" and not client.utc_tz_aware:
        return None
    return name


def _convert_column(  # noqa: PLR0911
    chunked: pa.ChunkedArray,
    field: pa.Field,
    spec: _ArrowColumnSpec | None,
    client: Client,
) -> pd.Series:
    if pa.types.is_dictionary(chunked.type):
        chunked = chunked.cast(chunked.type.value_type)
    arrow_type = chunked.type

    if spec is None:
        # Helper columns outside the plan types: hash bucket or grouping index literal.
        if not pa.types.is_integer(arrow_type):
            raise _ArrowConversionError(f"Unexpected column {field.name!r} of type {arrow_type}")
        spec = _ArrowColumnSpec("int", field.nullable, arrow_type=arrow_type)

    kind = spec.kind
    if kind == "int":
        if not pa.types.is_integer(arrow_type):
            raise _ArrowConversionError(
                f"Column {field.name!r}: expected integers, got {arrow_type}"
            )
        if arrow_type != spec.arrow_type:
            chunked = chunked.cast(spec.arrow_type)
        if spec.nullable:
            return chunked.to_pandas(
                types_mapper={spec.arrow_type: _NULLABLE_INTEGER_DTYPES[spec.arrow_type]}.get
            )
        return chunked.to_pandas()

    if kind == "float":
        if not pa.types.is_floating(arrow_type):
            raise _ArrowConversionError(f"Column {field.name!r}: expected floats, got {arrow_type}")
        # query_df widens Nullable(Float32) to float64.
        target = pa.float64() if spec.nullable else spec.arrow_type
        if arrow_type != target:
            chunked = chunked.cast(target)
        return chunked.to_pandas()

    if kind == "bool":
        if pa.types.is_integer(arrow_type):
            chunked = chunked.cast(pa.bool_())
        elif not pa.types.is_boolean(arrow_type):
            raise _ArrowConversionError(f"Column {field.name!r}: expected bool, got {arrow_type}")
        # bool without nulls, object with None/True/False otherwise, as query_df.
        return chunked.to_pandas()

    if kind == "string":
        if pa.types.is_binary(arrow_type) or pa.types.is_large_binary(arrow_type):
            # The cast validates UTF-8.
            chunked = chunked.cast(
                pa.large_string() if pa.types.is_large_binary(arrow_type) else pa.string()
            )
        elif pa.types.is_string(arrow_type) or pa.types.is_large_string(arrow_type):
            # ClickHouse does not validate UTF-8 in Arrow strings; query_df renders invalid
            # values as hex, so an invalid segment is re-read through query_df.
            chunked.validate(full=True)
        else:
            raise _ArrowConversionError(
                f"Column {field.name!r}: expected strings, got {arrow_type}"
            )
        return chunked.to_pandas(types_mapper={chunked.type: pd.StringDtype()}.get)

    if kind == "date":
        if pa.types.is_integer(arrow_type):
            # Date arrives as UInt16 days since the epoch.
            chunked = chunked.cast(pa.int32()).cast(pa.date32())
        elif not (pa.types.is_date(arrow_type) or pa.types.is_timestamp(arrow_type)):
            raise _ArrowConversionError(f"Column {field.name!r}: expected dates, got {arrow_type}")
        # Naive nanoseconds like query_df; out-of-range values raise ArrowInvalid.
        return chunked.cast(pa.timestamp("ns")).to_pandas()

    if kind == "datetime":
        if pa.types.is_integer(arrow_type):
            # DateTime arrives as UInt32 seconds since the epoch.
            chunked = chunked.cast(pa.int64()).cast(pa.timestamp("s", tz="UTC"))
        elif not pa.types.is_timestamp(arrow_type):
            raise _ArrowConversionError(
                f"Column {field.name!r}: expected timestamps, got {arrow_type}"
            )
        # Casting keeps the instant and relabels the timezone; naive output is UTC wall clock.
        return chunked.cast(pa.timestamp("ns", tz=_target_timezone(spec, client))).to_pandas()

    if kind == "decimal":
        if not pa.types.is_decimal(arrow_type):
            raise _ArrowConversionError(
                f"Column {field.name!r}: expected decimals, got {arrow_type}"
            )
        # Python Decimal objects (object dtype) with None for nulls, as query_df.
        return chunked.to_pandas()

    raise _ArrowConversionError(f"Unsupported Arrow conversion kind {kind!r}")


def _arrow_table_to_pandas(
    table: pa.Table,
    specs: Mapping[str, _ArrowColumnSpec],
    client: Client,
) -> pd.DataFrame:
    names = table.column_names
    if len(set(names)) != len(names):
        raise _ArrowConversionError(f"Duplicate result column names: {names!r}")
    normalized_specs = {
        SQLReadExecutor._normalize_column_name(name): spec for name, spec in specs.items()
    }
    fields = list(table.schema)
    columns = list(table.columns)
    del table

    converted: dict[str, pd.Series] = {}
    for index, name in enumerate(names):
        chunked = columns[index]
        # Drop the Arrow column as soon as it is converted to keep the peak memory down.
        columns[index] = None
        spec = specs.get(name) or normalized_specs.get(SQLReadExecutor._normalize_column_name(name))
        converted[name] = _convert_column(chunked, fields[index], spec, client)
        del chunked
    return pd.DataFrame(converted, copy=False)


def _query_arrow_table(client: Client, sql: str) -> pa.Table:
    # Client.query_arrow decodes into the default Arrow pool (mimalloc/jemalloc), whose
    # retention across dask threads raised the peak RSS of a 5M-row read from ~0.6 to ~1.0 GB;
    # the system allocator keeps it at the query_df level. Without query_arrow's
    # output_format_arrow_string_as_string override, a server that keeps it at 0 returns Binary,
    # which _convert_column casts to string with UTF-8 validation.
    data = client.raw_query(sql, fmt="Arrow")
    reader = pa.ipc.open_file(pa.py_buffer(data), memory_pool=pa.system_memory_pool())
    return reader.read_all()


class _ClickHouseClientPool:
    """Idle clickhouse_connect clients of one executor, each lent to one thread at a time.

    Creating a client costs server round trips (version, timezone, ``system.settings``, protocol
    probe). A client keeps an auto-generated HTTP session and rejects concurrent queries in it,
    so a client is never shared by running queries; all clients use the process-wide bounded
    urllib3 PoolManager behind ``create_clickhouse_client``.
    """

    def __init__(self, client_kwargs: Mapping[str, object], max_clients: int) -> None:
        self._client_kwargs = dict(client_kwargs)
        self._max_clients = max(1, max_clients)
        self._idle: list[Client] = []
        self._lock = Lock()

    @contextmanager
    def acquire(self) -> Iterator[Client]:
        with self._lock:
            client = self._idle.pop() if self._idle else None
        if client is None:
            client = create_clickhouse_client(self._client_kwargs)
        try:
            yield client
        except BaseException:
            # Do not reuse a client whose query failed or was interrupted.
            client.close()
            raise
        with self._lock:
            if len(self._idle) < self._max_clients:
                self._idle.append(client)
                return
        client.close()


class ClickHouseReadExecutor(SQLReadExecutor):
    def __init__(
        self,
        engine: Engine,
        *,
        dialect: SQLDialect | None = None,
        max_concurrent_queries: int | None = None,
    ):
        super().__init__(engine, dialect=dialect, max_concurrent_queries=max_concurrent_queries)
        self._client_pool = _ClickHouseClientPool(
            build_clickhouse_client_kwargs(engine),
            max_clients=max_concurrent_queries or _DEFAULT_CLIENT_POOL_SIZE,
        )

    def _fetch_segment_df(self, sql: str, plan: ReadV3Plan) -> pd.DataFrame:
        specs = _segment_arrow_specs(plan)
        with self._client_pool.acquire() as client:
            if specs is None:
                return client.query_df(sql)
            try:
                return _arrow_table_to_pandas(_query_arrow_table(client, sql), specs, client)
            except (_ArrowConversionError, *_ARROW_CONVERSION_ERRORS) as exc:
                logger.warning(
                    "read_v3 ClickHouse Arrow result of %s is re-read through query_df: %s",
                    plan.source_name(),
                    exc,
                )
                return client.query_df(sql)
