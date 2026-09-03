from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ParquetWriteMode(StrEnum):
    CREATE = "create"
    OVERWRITE = "overwrite"
    APPEND = "append"


class ParquetLayout(StrEnum):
    SIMPLE = "simple"
    ADVANCED = "advanced"


@dataclass(frozen=True, slots=True)
class ParquetWriteRequest:
    path: str
    mode: ParquetWriteMode | str
    filename_template: str | None = None
    row_cap: int | None = None
    partition_on: tuple[str, ...] | list[str] | None = None
    compression: str | None = "snappy"
    write_index: bool = False
    parquet_types: dict[str, str] | None = None
    write_workers: int = 2

    @property
    def normalized_mode(self) -> ParquetWriteMode:
        return ParquetWriteMode(self.mode)

    @property
    def normalized_partition_on(self) -> tuple[str, ...]:
        return tuple(self.partition_on or ())

    @property
    def layout(self) -> ParquetLayout:
        if (
            self.filename_template is None
            and self.row_cap is None
            and not self.normalized_partition_on
            and self.normalized_mode is not ParquetWriteMode.APPEND
        ):
            return ParquetLayout.SIMPLE
        return ParquetLayout.ADVANCED


@dataclass(slots=True)
class ParquetWriteResult:
    layout: ParquetLayout
    rows_written: int
    files_written: int
    paths: list[str] = field(default_factory=list)
