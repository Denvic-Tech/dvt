from __future__ import annotations

from uuid import uuid4

import dask.dataframe as dd
import pandas as pd
import sqlalchemy as sa

from core.db.write_v3.dask import process_partitions_bounded
from core.db.write_v3.errors import WriteV3ExecutionError
from core.db.write_v3.executors.base import WriteExecutor
from core.db.write_v3.models import WritePlan, WriteRequest, WriteResult
from core.db.write_v3.normalize import ColumnAlignment, align_partition_to_table

_DIRECT_TRUNCATE_DIALECTS = {"postgresql", "mysql", "mssql", "clickhouse"}


class SQLWriteExecutor(WriteExecutor):
    def execute(self, ddf: dd.DataFrame, request: WriteRequest, plan: WritePlan) -> WriteResult:
        table = self._reflect_table(request.target.table_name, request.target.schema_name)
        request_alignment = self._normalize_partition(
            ddf._meta,
            table,
            request,
            include_default_only_diagnostic=False,
        )
        diagnostics = request_alignment.diagnostics
        copy_column_names = request_alignment.insert_column_names

        if plan.mode == "append":
            written = process_partitions_bounded(
                ddf,
                lambda pdf: self._insert_partition(table, pdf, request),
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
                lambda pdf: self._insert_partition(staging_table, pdf, request),
                max_workers=request.write_workers,
            )

            if plan.mode == "truncate":
                self._truncate_or_replace_table(table)
            else:
                delete_sql = self.dialect.delete_using_staging_sql(
                    target_table=table.name,
                    target_schema=table.schema,
                    staging_table=staging_table.name,
                    staging_schema=staging_table.schema,
                    key_column=plan.upsert_key or "",
                )
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

    def _reflect_table(self, table_name: str, schema_name: str | None) -> sa.Table:
        metadata = sa.MetaData()
        return sa.Table(table_name, metadata, schema=schema_name, autoload_with=self.engine)

    def _create_staging_table(self, target_table: sa.Table) -> sa.Table:
        staging_name = self._build_object_name(target_table.name, "stg")
        metadata = sa.MetaData(schema=target_table.schema)
        columns = []
        for column in target_table.columns:
            columns.append(
                sa.Column(
                    column.name,
                    column.type,
                    nullable=True,
                    quote=getattr(column.name, "quote", False),
                )
            )
        staging_table = sa.Table(staging_name, metadata, *columns)
        staging_table.create(self.engine, checkfirst=False)
        if hasattr(target_table, "rename_map"):
            staging_table.rename_map = getattr(target_table, "rename_map")
        return staging_table

    def _insert_partition(self, table: sa.Table, pdf: pd.DataFrame, request: WriteRequest) -> int:
        alignment = self._normalize_partition(pdf, table, request)
        if alignment.row_count == 0:
            return 0

        if alignment.default_only_insert:
            return self._insert_default_only_rows(table, alignment.row_count, request.chunksize)

        total_rows = alignment.row_count
        chunk_rows = request.chunksize or total_rows
        for start in range(0, total_rows, chunk_rows):
            chunk = alignment.normalized.iloc[start: start + chunk_rows]
            records = chunk.to_dict(orient="records")
            with self.engine.begin() as conn:
                conn.execute(sa.insert(table), records)
        return total_rows

    def _normalize_partition(
        self,
        pdf: pd.DataFrame,
        table: sa.Table,
        request: WriteRequest,
        *,
        include_default_only_diagnostic: bool = True,
    ) -> ColumnAlignment:
        return align_partition_to_table(
            pdf,
            table,
            request,
            include_default_only_diagnostic=include_default_only_diagnostic,
        )

    def _insert_default_only_rows(self, table: sa.Table, row_count: int, chunksize: int | None) -> int:
        chunk_rows = chunksize or row_count
        with self.engine.begin() as conn:
            for start in range(0, row_count, chunk_rows):
                batch_rows = min(chunk_rows, row_count - start)
                stmt = sa.insert(table).values({})
                for _ in range(batch_rows):
                    conn.execute(stmt)
        return row_count

    def _copy_table(
        self,
        source_table: sa.Table,
        target_table: sa.Table,
        column_names: list[str] | None = None,
    ) -> None:
        if column_names is None:
            column_names = [column.name for column in target_table.columns if column.name in source_table.c]
        insert_stmt = target_table.insert().from_select(
            column_names,
            sa.select(*[source_table.c[name] for name in column_names]),
        )
        with self.engine.begin() as conn:
            conn.execute(insert_stmt)

    def _truncate_or_replace_table(self, target_table: sa.Table) -> None:
        if self.dialect.name in _DIRECT_TRUNCATE_DIALECTS:
            with self.engine.begin() as conn:
                conn.execute(sa.text(self.dialect.truncate_sql(target_table.name, target_table.schema)))
            return

        replacement_table = self._create_empty_replacement_table(target_table)
        replacement_swapped = False
        try:
            self._replace_table_with_copy(target_table, replacement_table)
            replacement_swapped = True
        finally:
            if not replacement_swapped:
                try:
                    self._drop_table(replacement_table)
                except Exception:
                    pass

    def _create_empty_replacement_table(self, target_table: sa.Table) -> sa.Table:
        replacement_name = self._build_object_name(target_table.name, "empty")
        metadata = sa.MetaData(schema=target_table.schema)
        replacement_table = target_table.to_metadata(metadata, name=replacement_name)
        replacement_table.create(self.engine, checkfirst=False)
        return replacement_table

    def _replace_table_with_copy(self, target_table: sa.Table, replacement_table: sa.Table) -> None:
        rename_sql = self._rename_table_sql(
            source_name=replacement_table.name,
            source_schema=replacement_table.schema,
            target_name=target_table.name,
        )
        with self.engine.begin() as conn:
            target_table.drop(bind=conn, checkfirst=False)
            conn.execute(sa.text(rename_sql))

    def _drop_table(self, table: sa.Table) -> None:
        try:
            table.drop(self.engine, checkfirst=True)
        except Exception as exc:  # pragma: no cover - best effort cleanup
            raise WriteV3ExecutionError(
                f"Failed to drop temporary table '{table.fullname}': {exc}"
            ) from exc

    @staticmethod
    def _build_object_name(base_name: str, prefix: str) -> str:
        return f"{base_name}_{prefix}_{uuid4().hex[:8]}"

    def _rename_table_sql(self, *, source_name: str, source_schema: str | None, target_name: str) -> str:
        source_full = self.dialect.full_table_name(source_name, source_schema)
        target_ident = self.dialect.quote_ident(target_name)
        return f"ALTER TABLE {source_full} RENAME TO {target_ident}"
