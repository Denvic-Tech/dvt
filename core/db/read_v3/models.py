from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from typing import Any, Optional

from core.db.read_v3.datetime_precision import ReadV3DateTimePrecision


class ReadMode(StrEnum):
    TABLE = "table"
    QUERY = "query"


class PartitionStrategy(StrEnum):
    RANGE = "range"
    HASH = "hash"


class ValueKind(StrEnum):
    NUMERIC = "numeric"
    DATE = "date"
    DATETIME = "datetime"
    STRING = "string"
    BOOL = "bool"
    UUID = "uuid"
    JSON = "json"
    UNKNOWN = "unknown"


SUPPORTED_OUTPUT_VALUE_KINDS = frozenset(
    {
        ValueKind.NUMERIC,
        ValueKind.DATE,
        ValueKind.DATETIME,
        ValueKind.STRING,
        ValueKind.BOOL,
        ValueKind.UUID,
        ValueKind.JSON,
    }
)


@dataclass(frozen=True)
class SegmentDivision:
    start: Any
    end: Any
    include_end: bool = False


@dataclass
class ReadSegment:
    label: str
    predicate_sql: str
    order_by_sql: str
    division: SegmentDivision
    strategy: PartitionStrategy
    expected_rows: int | None = None
    bucket_start: int | None = None
    bucket_end: int | None = None
    index_literal: int | None = None


@dataclass
class ReadV3Plan:
    mode: ReadMode
    dialect: str
    cte_prefix_sql: str | None
    relation_sql: str
    select_exprs: Sequence[str]
    output_columns: Sequence[str]
    partition_key_name: str
    partition_key_kind: ValueKind
    strategy: PartitionStrategy
    segments: list[ReadSegment]
    divisions: tuple[Any, ...]
    max_rows_per_partition: int
    partition_key_type_repr: str = ""
    partition_key_alias: str = "__dvt_partition_key"
    hash_bucket_alias: str = "__dvt_partition_bucket"
    index_column_name: str = "__dvt_partition_key"
    total_rows: int | None = None
    npartitions: int | None = None
    output_column_kinds: dict[str, ValueKind] = field(default_factory=dict)
    output_column_type_repr: dict[str, str] = field(default_factory=dict)
    output_column_sql_names: dict[str, str] = field(default_factory=dict)
    output_column_select_exprs: dict[str, str] = field(default_factory=dict)
    partition_key_sql_name: str = ""
    extra_warnings: list[str] = field(default_factory=list)
    source_table_name: str | None = None
    source_schema_name: str | None = None
    datetime_precision: ReadV3DateTimePrecision = ReadV3DateTimePrecision.MICROSECONDS

    def select_list_sql(self) -> str:
        return ", ".join(self.select_exprs)

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    def source_name(self) -> str:
        if self.source_table_name:
            if self.source_schema_name:
                return f"{self.source_schema_name}.{self.source_table_name}"
            return self.source_table_name
        if self.mode == ReadMode.QUERY:
            return "user_query"
        return self.relation_sql
