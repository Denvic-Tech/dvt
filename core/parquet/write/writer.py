from __future__ import annotations

import contextlib
import posixpath
import threading
from dataclasses import dataclass, field

import dask
import dask.dataframe as dd
import pandas as pd
import pyarrow.parquet as pq

from core.parquet.write.dask import (
    compute_with_dataframe_callbacks,
    find_source_paths,
    flatten_delayed_partitions,
)
from core.parquet.write.filesystem import ParquetFilesystem
from core.parquet.write.models import (
    ParquetLayout,
    ParquetWriteMode,
    ParquetWriteRequest,
    ParquetWriteResult,
)
from core.parquet.write.naming import IncrementAllocator, NamingContext
from core.parquet.write.partitioning import iter_physical_chunks, validate_partition_columns
from core.parquet.write.planner import plan_advanced_write, prepare_advanced_target
from core.parquet.write.schema import (
    ParquetDatasetSchema,
    build_dataset_schema,
    build_empty_partitioned_sentinel_schema,
    ensure_append_dataset_compatible,
    read_file_dataset_schema,
    table_from_pandas,
)
from core.types import FsCtx


@dataclass(slots=True)
class _WriteTracker:
    attempted_paths: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, path: str) -> None:
        with self._lock:
            self.attempted_paths.append(path)

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self.attempted_paths)


@dataclass(slots=True)
class _SimpleWriterSession:
    writer: pq.ParquetWriter
    schema: object
    write_index: bool


@dataclass(frozen=True, slots=True)
class _PartitionWriteResult:
    rows: int
    paths: tuple[str, ...]


def write_dataframe(
        ddf: dd.DataFrame,
        fs_context: FsCtx,
        request: ParquetWriteRequest,
) -> ParquetWriteResult:
    """Write a Dask DataFrame without materializing the full dataset in memory.

    Concurrent append from independent Task Workers is intentionally not coordinated in V1.
    Callers must serialize writes to the same dataset when collision-free append is required.
    """
    _validate_request(request)
    filesystem = ParquetFilesystem(fs_context)
    if request.layout is ParquetLayout.SIMPLE:
        return _write_simple(ddf, filesystem, request)
    return _write_advanced(ddf, filesystem, request)


def _validate_request(request: ParquetWriteRequest) -> None:
    raw_path = (request.path or "").strip().replace("\\", "/")
    if not raw_path or raw_path in {"/", ".", ".."}:
        raise ValueError("Parquet target path must point below the File Connection root.")
    if raw_path.startswith("/") or "://" in raw_path:
        raise ValueError("Parquet target path must be relative to the File Connection root.")
    if any(part in {"", ".", ".."} for part in raw_path.strip("/").split("/")):
        raise ValueError("Parquet target path contains an unsafe path segment.")
    validate_partition_columns(request.normalized_partition_on)
    if request.row_cap is not None and int(request.row_cap) < 1:
        raise ValueError("Input 'row_cap' must be >= 1.")
    if request.write_workers < 1:
        raise ValueError("write_workers must be >= 1.")


def _write_simple(
        ddf: dd.DataFrame,
        filesystem: ParquetFilesystem,
        request: ParquetWriteRequest,
) -> ParquetWriteResult:
    mode = request.normalized_mode
    if mode is ParquetWriteMode.APPEND:
        raise ValueError("Append is supported only for Advanced Parquet layout.")

    target = filesystem.target
    if not target.lower().endswith(".parquet"):
        raise ValueError("Simple Parquet target must resolve to a '.parquet' physical file.")

    existed = filesystem.exists(target)
    if existed and filesystem.isdir(target):
        raise ValueError(
            f"Cannot write Simple Parquet file at '{request.path}': target exists as a directory."
        )
    if mode is ParquetWriteMode.CREATE and existed:
        raise FileExistsError(
            f"Cannot create Parquet file at '{request.path}': target file already exists. "
            "Use mode='overwrite' to replace it."
        )

    dataset_schema = build_dataset_schema(
        ddf._meta_nonempty,
        write_index=request.write_index,
        parquet_types=request.parquet_types,
    )
    compression = None if request.compression in {None, "none"} else request.compression
    _validate_overwrite_source_overlap(ddf, filesystem, request)
    filesystem.ensure_parent(target)

    writer = None
    handle = None
    try:
        handle = filesystem.open(target, "wb")
        writer = pq.ParquetWriter(handle, schema=dataset_schema.physical, compression=compression)
        session = _SimpleWriterSession(
            writer=writer,
            schema=dataset_schema.physical,
            write_index=request.write_index,
        )

        # A single physical ParquetWriter must be serialized. Keeping the whole chain in one
        # Dask computation still guarantees shared-upstream reuse, while the synchronous local
        # scheduler keeps only the currently-needed partition live.
        chain = dask.delayed(lambda: 0, pure=False)()
        for delayed_part in flatten_delayed_partitions(ddf):
            chain = dask.delayed(_append_simple_partition, pure=False)(
                chain,
                delayed_part,
                session,
            )
        rows_written = int(
            compute_with_dataframe_callbacks(ddf, chain, max_workers=1)[0]
        )
    except Exception:
        if writer is not None:
            with contextlib.suppress(Exception):
                writer.close()
        if handle is not None:
            with contextlib.suppress(Exception):
                handle.close()
        filesystem.remove_file(target)
        raise
    else:
        writer.close()
        handle.close()

    return ParquetWriteResult(
        layout=ParquetLayout.SIMPLE,
        rows_written=rows_written,
        files_written=1,
        paths=[target],
    )


def _append_simple_partition(
        previous_rows: int,
        pdf: pd.DataFrame,
        session: _SimpleWriterSession,
) -> int:
    table = table_from_pandas(pdf, session.schema, write_index=session.write_index)
    if table.num_rows:
        session.writer.write_table(table)
    return int(previous_rows) + int(table.num_rows)


def _write_advanced(
        ddf: dd.DataFrame,
        filesystem: ParquetFilesystem,
        request: ParquetWriteRequest,
) -> ParquetWriteResult:
    dataset_schema = build_dataset_schema(
        ddf._meta_nonempty,
        write_index=request.write_index,
        parquet_types=request.parquet_types,
        partition_on=request.normalized_partition_on,
    )
    plan = plan_advanced_write(filesystem, request, source_partitions=ddf.npartitions)
    if plan.mode is ParquetWriteMode.APPEND:
        for existing_path in plan.existing_files:
            ensure_append_dataset_compatible(
                dataset_schema,
                read_file_dataset_schema(filesystem, existing_path),
                path=existing_path,
            )

    _validate_overwrite_source_overlap(ddf, filesystem, request)
    prepare_advanced_target(filesystem, plan)

    allocator = IncrementAllocator(plan.start_increment)
    compression = None if request.compression in {None, "none"} else request.compression
    tracker = _WriteTracker()
    workers = _effective_workers(request.write_workers, filesystem.ctx.protocol)
    tasks = [
        dask.delayed(_write_advanced_partition, pure=False)(
            partition_index,
            delayed_part,
            filesystem,
            plan.root,
            plan.template,
            allocator,
            tracker,
            dataset_schema,
            request.row_cap,
            request.normalized_partition_on,
            request.write_index,
            compression,
        )
        for partition_index, delayed_part in enumerate(flatten_delayed_partitions(ddf))
    ]

    try:
        results = (
            compute_with_dataframe_callbacks(ddf, *tasks, max_workers=workers)
            if tasks
            else ()
        )
        created_paths = [path for result in results for path in result.paths]
        rows_written = sum(result.rows for result in results)

        if not created_paths and plan.mode is not ParquetWriteMode.APPEND:
            increment = allocator.next()
            filename = plan.template.render(NamingContext(partition_index=0, increment=increment))
            path = posixpath.join(plan.root, filename)
            tracker.add(path)
            sentinel_schema = (
                build_empty_partitioned_sentinel_schema(dataset_schema)
                if request.normalized_partition_on
                else dataset_schema.physical
            )
            rows_written += _write_one_file(
                filesystem,
                path,
                ddf._meta.copy(),
                schema=sentinel_schema,
                write_index=request.write_index,
                compression=compression,
            )
            created_paths.append(path)
    except Exception:
        attempted_paths = tracker.snapshot()
        for path in attempted_paths:
            filesystem.remove_file(path)
        filesystem.cleanup_empty_parents(attempted_paths, plan.root)
        raise

    return ParquetWriteResult(
        layout=ParquetLayout.ADVANCED,
        rows_written=int(rows_written),
        files_written=len(created_paths),
        paths=created_paths,
    )


def _write_advanced_partition(
        partition_index: int,
        pdf: pd.DataFrame,
        filesystem: ParquetFilesystem,
        root: str,
        template,
        allocator: IncrementAllocator,
        tracker: _WriteTracker,
        dataset_schema: ParquetDatasetSchema,
        row_cap: int | None,
        partition_on: tuple[str, ...],
        write_index: bool,
        compression: str | None,
) -> _PartitionWriteResult:
    rows_written = 0
    created_paths: list[str] = []
    for relative_dir, chunk in iter_physical_chunks(
            pdf,
            row_cap=row_cap,
            partition_on=partition_on,
            partition_schema=dataset_schema.partition,
    ):
        increment = allocator.next()
        filename = template.render(
            NamingContext(partition_index=partition_index, increment=increment)
        )
        path = (
            posixpath.join(root, relative_dir, filename)
            if relative_dir
            else posixpath.join(root, filename)
        )
        filesystem.assert_descendant(path, root)
        if filesystem.exists(path):
            raise FileExistsError(
                f"Parquet filename collision at '{path}'. No existing file was overwritten."
            )
        tracker.add(path)
        physical_partition_columns = [
            column for column in partition_on if column in dataset_schema.physical.names
        ]
        physical_chunk = (
            chunk
            if physical_partition_columns
            else chunk.drop(columns=list(partition_on), errors="ignore")
        )
        rows_written += _write_one_file(
            filesystem,
            path,
            physical_chunk,
            schema=dataset_schema.physical,
            write_index=write_index,
            compression=compression,
        )
        created_paths.append(path)
    return _PartitionWriteResult(rows=rows_written, paths=tuple(created_paths))


def _write_one_file(
        filesystem: ParquetFilesystem,
        path: str,
        pdf: pd.DataFrame,
        *,
        schema,
        write_index: bool,
        compression: str | None,
) -> int:
    filesystem.ensure_parent(path)
    table = table_from_pandas(pdf, schema, write_index=write_index)
    try:
        with filesystem.open(path, "wb") as handle:
            pq.write_table(table, handle, compression=compression)
    except Exception:
        filesystem.remove_file(path)
        raise
    return int(table.num_rows)


def _validate_overwrite_source_overlap(
        ddf: dd.DataFrame,
        filesystem: ParquetFilesystem,
        request: ParquetWriteRequest,
) -> None:
    if request.normalized_mode is not ParquetWriteMode.OVERWRITE:
        return

    target = filesystem.target
    for source_path in find_source_paths(ddf):
        if filesystem.paths_overlap(source_path, target):
            raise ValueError(
                f"Cannot overwrite Parquet target '{request.path}' because the input DataFrame "
                "reads from the same target. Read and write paths must not overlap in the same "
                "execution."
            )


def _effective_workers(requested: int, protocol: str) -> int:
    if protocol in {"ftp", "sftp", "smb"}:
        return 1
    return max(1, int(requested))
