from __future__ import annotations

from contextlib import contextmanager
from threading import Lock
from uuid import uuid4

import dask.dataframe as dd
import pandas as pd
import sqlalchemy as sa
from clickhouse_connect.driver import Client

from core.db.connect import build_clickhouse_client_kwargs, create_clickhouse_client
from core.db.write_v3.dask import process_partitions_bounded
from core.db.write_v3.executors.base import WriteExecutor
from core.db.write_v3.models import WritePlan, WriteRequest, WriteResult
from core.db.write_v3.normalize import ColumnAlignment, align_partition_to_table


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
                        use_async_insert=True,
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

        staging_table = self._reflect_table(staging_name, table.schema)
        if hasattr(table, "rename_map"):
            staging_table.rename_map = getattr(table, "rename_map")
        return staging_table

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
        total_rows = alignment.row_count
        chunk_rows = request.chunksize or total_rows

        for start in range(0, total_rows, chunk_rows):
            chunk = alignment.normalized.iloc[start: start + chunk_rows]
            column_data = self._prepare_column_data(chunk, column_order, column_meta)
            with pool.acquire() as client:
                settings = {
                    "input_format_null_as_default": 1,
                }
                if use_async_insert:
                    settings["async_insert"] = 1
                    settings["wait_for_async_insert"] = 1
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

    def _normalize_partition(
        self,
        pdf: pd.DataFrame,
        table: sa.Table,
        request: WriteRequest,
        *,
        include_default_only_diagnostic: bool = True,
    ) -> ColumnAlignment:
        alignment = align_partition_to_table(
            pdf,
            table,
            request,
            include_default_only_diagnostic=include_default_only_diagnostic,
        )
        working = alignment.normalized.copy()
        for column in working.columns:
            if pd.api.types.is_datetime64_any_dtype(working[column]):
                null_mask = working[column].isna()
                if null_mask.any():
                    working[column] = working[column].astype(object)
                    working.loc[null_mask, column] = None
        alignment.normalized = working
        return alignment

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
                "is_datetime": "datetime" in raw_type.lower(),
            }
        return meta

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
    ) -> list:
        data: list = []
        for column in column_order:
            series = pdf[column]
            meta = column_meta[column]
            base_type = str(meta["base_type"])
            if meta["is_datetime"]:
                data.append([self._normalize_datetime_value(value, base_type) for value in series.tolist()])
            elif self._is_string_like(base_type):
                data.append([self._normalize_string_value(value) for value in series.tolist()])
            elif series.dtype == object:
                data.append(series.where(series.notna(), None).tolist())
            else:
                data.append(series.values)
        return data

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
