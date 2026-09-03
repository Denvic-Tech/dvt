from __future__ import annotations

import posixpath
from dataclasses import dataclass

from core.parquet.write.filesystem import ParquetFilesystem
from core.parquet.write.models import ParquetWriteMode, ParquetWriteRequest
from core.parquet.write.naming import FilenameTemplate


@dataclass(frozen=True, slots=True)
class AdvancedWritePlan:
    root: str
    mode: ParquetWriteMode
    template: FilenameTemplate
    existing_files: tuple[str, ...]
    start_increment: int


def plan_advanced_write(
    filesystem: ParquetFilesystem,
    request: ParquetWriteRequest,
    *,
    source_partitions: int,
) -> AdvancedWritePlan:
    """Validate and inspect an Advanced write without mutating the filesystem."""

    root = filesystem.target.rstrip("/")
    mode = request.normalized_mode
    if posixpath.basename(root).lower().endswith(".parquet"):
        raise ValueError(
            "Advanced Parquet path must point to a dataset directory, not to a .parquet file. "
            "Use e.g. 'reports/orders' instead of 'reports/orders.parquet'."
        )

    template = FilenameTemplate(request.filename_template)
    template.validate_uniqueness(
        mode=mode,
        source_partitions=source_partitions,
        row_cap=request.row_cap,
        partition_on=request.normalized_partition_on,
    )
    existing_files = tuple(_inspect_target(filesystem, root, request))
    start_increment = (
        _next_increment(existing_files, template) if mode is ParquetWriteMode.APPEND else 0
    )
    return AdvancedWritePlan(
        root=root,
        mode=mode,
        template=template,
        existing_files=existing_files,
        start_increment=start_increment,
    )


def prepare_advanced_target(
    filesystem: ParquetFilesystem,
    plan: AdvancedWritePlan,
) -> None:
    """Perform filesystem mutations only after all write preflight checks pass."""

    if plan.mode is ParquetWriteMode.CREATE:
        filesystem.ensure_directory(plan.root)
        return
    if plan.mode is ParquetWriteMode.OVERWRITE:
        if filesystem.exists(plan.root) or filesystem.list_recursive(plan.root):
            filesystem.remove_tree(plan.root)
        filesystem.ensure_directory(plan.root)


def _inspect_target(
    filesystem: ParquetFilesystem,
    root: str,
    request: ParquetWriteRequest,
) -> list[str]:
    mode = request.normalized_mode
    target_exists = filesystem.exists(root)
    if target_exists and not filesystem.isdir(root):
        raise ValueError(
            f"Advanced Parquet target '{request.path}' exists as a file; a dataset directory is required."
        )

    objects = filesystem.list_recursive(root)
    if mode is ParquetWriteMode.CREATE:
        if filesystem.is_non_empty_directory(root):
            raise FileExistsError(
                f"Cannot create Parquet dataset at '{request.path}': target directory is not empty. "
                "Use mode='overwrite' to replace existing contents or choose another path."
            )
        return []

    if mode is ParquetWriteMode.OVERWRITE:
        return []

    if not target_exists and not objects:
        raise FileNotFoundError(
            f"Cannot append Parquet dataset at '{request.path}': target dataset does not exist. "
            "Use mode='create' first."
        )
    parquet_files = [path for path in objects if path.lower().endswith(".parquet")]
    if not parquet_files:
        raise ValueError(
            f"Cannot append Parquet dataset at '{request.path}': target does not contain Parquet files. "
            "Use mode='create' first."
        )
    return parquet_files


def _next_increment(existing_files: tuple[str, ...], template: FilenameTemplate) -> int:
    max_increment = -1
    for path in existing_files:
        value = template.extract_increment(posixpath.basename(path))
        if value is not None:
            max_increment = max(max_increment, value)
    return max_increment + 1
