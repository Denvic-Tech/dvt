from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, Field, field_validator, model_validator

from core.types import DBColumn


class IndexSpec(BaseModel):
    name: str | None = None
    columns: list[str] = Field(min_length=1)
    unique: bool = False


class ForeignKeySpec(BaseModel):
    name: str | None = None
    columns: list[str] = Field(min_length=1)
    ref_table: str
    ref_schema: str | None = None
    ref_columns: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_lengths(self) -> "ForeignKeySpec":
        if len(self.columns) != len(self.ref_columns):
            raise ValueError("Foreign key column counts must match.")
        return self


ClickHouseEngineName: TypeAlias = Literal[
    "MergeTree",
    "ReplacingMergeTree",
    "SummingMergeTree",
    "AggregatingMergeTree",
    "CollapsingMergeTree",
    "VersionedCollapsingMergeTree",
    "ReplicatedMergeTree",
    "ReplicatedReplacingMergeTree",
    "ReplicatedSummingMergeTree",
    "ReplicatedAggregatingMergeTree",
    "ReplicatedCollapsingMergeTree",
    "ReplicatedVersionedCollapsingMergeTree",
]


ClickHouseSettingValue: TypeAlias = str | int | float | bool


class ClickHouseEngineSpec(BaseModel):
    engine_name: ClickHouseEngineName = "MergeTree"
    order_by: list[str] | None = None
    partition_by: list[str] | None = None
    primary_key: list[str] | None = None
    sample_by: list[str] | None = None
    ttl_expression: str | None = None
    version_column: str | None = None
    sign_column: str | None = None
    summing_columns: list[str] | None = None
    table_path: str | None = None
    replica_name: str | None = None
    settings: dict[str, ClickHouseSettingValue] | None = None

    @model_validator(mode="after")
    def validate_engine_contract(self) -> "ClickHouseEngineSpec":
        replicated_engines = {
            "ReplicatedMergeTree",
            "ReplicatedReplacingMergeTree",
            "ReplicatedSummingMergeTree",
            "ReplicatedAggregatingMergeTree",
            "ReplicatedCollapsingMergeTree",
            "ReplicatedVersionedCollapsingMergeTree",
        }
        replacing_engines = {"ReplacingMergeTree", "ReplicatedReplacingMergeTree"}
        summing_engines = {"SummingMergeTree", "ReplicatedSummingMergeTree"}
        collapsing_engines = {"CollapsingMergeTree", "ReplicatedCollapsingMergeTree"}
        versioned_engines = {
            "VersionedCollapsingMergeTree",
            "ReplicatedVersionedCollapsingMergeTree",
        }
        engines_with_optional_version = replacing_engines | versioned_engines

        if self.engine_name in replicated_engines:
            if not self.table_path:
                raise ValueError("table_path is required for replicated ClickHouse engines.")
            if not self.replica_name:
                raise ValueError("replica_name is required for replicated ClickHouse engines.")
        elif self.table_path is not None or self.replica_name is not None:
            raise ValueError("table_path and replica_name are allowed only for replicated ClickHouse engines.")

        if self.engine_name in collapsing_engines | versioned_engines:
            if not self.sign_column:
                raise ValueError("sign_column is required for collapsing ClickHouse engines.")
        elif self.sign_column is not None:
            raise ValueError("sign_column is allowed only for collapsing ClickHouse engines.")

        if self.engine_name in versioned_engines:
            if not self.version_column:
                raise ValueError("version_column is required for versioned collapsing ClickHouse engines.")
        elif self.version_column is not None and self.engine_name not in replacing_engines:
            raise ValueError(
                "version_column is allowed only for replacing or versioned collapsing ClickHouse engines."
            )

        if self.engine_name in summing_engines:
            if self.summing_columns is not None and not self.summing_columns:
                raise ValueError("summing_columns must not be empty when provided.")
        elif self.summing_columns is not None:
            raise ValueError("summing_columns is allowed only for summing ClickHouse engines.")

        if self.order_by is not None and not self.order_by:
            raise ValueError("order_by must not be empty when provided.")
        if self.partition_by is not None and not self.partition_by:
            raise ValueError("partition_by must not be empty when provided.")
        if self.primary_key is not None and not self.primary_key:
            raise ValueError("primary_key must not be empty when provided.")
        if self.sample_by is not None and not self.sample_by:
            raise ValueError("sample_by must not be empty when provided.")

        return self


class TableCreateSpec(BaseModel):
    primary_key_cols: str | list[str] | None = None
    indexes: list[IndexSpec] | None = None
    foreign_keys: list[ForeignKeySpec] | None = None
    clickhouse: ClickHouseEngineSpec | None = None


TableColumnActionType: TypeAlias = Literal[
    "add_column",
    "drop_column",
    "recreate_column",
]


class TableColumnAction(BaseModel):
    type: TableColumnActionType
    column_name: str = Field(min_length=1)
    column: DBColumn | None = None

    @field_validator("column_name")
    @classmethod
    def _strip_column_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("column_name must not be empty.")
        return normalized

    @model_validator(mode="after")
    def validate_action_contract(self) -> "TableColumnAction":
        if self.type in {"add_column", "recreate_column"}:
            if self.column is None:
                raise ValueError(f"column is required for {self.type}.")
            if self.column.name.strip() != self.column_name:
                raise ValueError("column.name must match column_name.")
        return self


class AppliedTableColumnAction(BaseModel):
    type: TableColumnActionType
    column_name: str
    sql: list[str]
