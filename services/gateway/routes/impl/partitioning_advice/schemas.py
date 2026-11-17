"""Transport schemas of the read partitioning advice (Gateway route and MCP facade)."""

from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Profiled values are returned as JSON scalars; dates and datetimes as ISO strings.
KeyValue = str | int | float | bool | None


class PartitioningAdviceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    database_name: str | None = Field(
        default=None, description="Source database; omit for the connection default."
    )
    schema_name: str | None = Field(default=None, description="Source schema (table mode).")
    table_name: str | None = Field(
        default=None, description="Table to profile; exclusive with sql_code."
    )
    sql_code: str | None = Field(
        default=None,
        description=(
            "Read-only SELECT/WITH query to profile as ReadQueryFromDBV3 embeds it; exclusive "
            "with table_name. Available for PostgreSQL, MySQL, Oracle and ClickHouse."
        ),
    )
    columns: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description=(
            "Candidate partition columns; omit to profile up to candidate_limit scalar columns, "
            "sort-key and index-leading columns first."
        ),
    )
    read_columns: list[str] | None = Field(
        default=None,
        min_length=1,
        description=(
            "Columns the reader selects (its `columns` input), for the row width estimate; "
            "omit for all columns."
        ),
    )
    candidate_limit: int = Field(default=20, ge=1, le=100)
    npartitions: int | None = Field(
        default=None, ge=1, description="Planned npartitions; omit for automatic sizing."
    )
    max_rows_per_partition: int | None = Field(
        default=None, ge=1, description="Planned ceiling; omit for the planner default."
    )

    @model_validator(mode="after")
    def _one_relation(self) -> Self:
        if (self.table_name is None) == (self.sql_code is None):
            raise ValueError("Provide exactly one of table_name or sql_code")
        if self.sql_code is not None and self.schema_name is not None:
            raise ValueError("schema_name applies to table_name only")
        return self


class KeyColumnStatsSchema(BaseModel):
    name: str
    type_repr: str
    value_kind: str
    available: bool
    source: Literal["exact", "approximate", "catalog", "sample"] | None
    estimated: bool
    distinct_count: int | None
    max_repeat: int | None
    max_repeat_value: KeyValue
    null_count: int | None
    min_value: KeyValue
    max_value: KeyValue
    indexed: bool
    note: str | None


class RelationKeyStatsSchema(BaseModel):
    mode: Literal["table", "query"]
    dialect: str
    relation: str
    total_rows: int
    total_rows_estimated: bool
    bytes_per_row_est: int
    read_columns: list[str]
    sort_key: str | None
    sample_method: str | None
    sample_rows: int | None
    sample_threshold_rows: int
    warnings: list[str]


class PartitionSizingSchema(BaseModel):
    total_rows: int
    total_rows_estimated: bool
    bytes_per_row_est: int
    target_npartitions: int
    npartitions_source: Literal["planner_estimate", "request"]
    target_rows_per_partition: int
    max_rows_per_partition: int
    max_rows_per_partition_source: Literal["planner_default", "request"]
    max_partitions: int


class GranularityOptionSchema(BaseModel):
    partition_grouping: dict[str, Any]
    periods_est: int
    rows_per_period_est: int
    note: str


class PartitionRecommendationSchema(BaseModel):
    rank: int
    partition_col: str
    strategy: Literal["range", "hash"]
    partition_grouping: dict[str, Any]
    npartitions: int
    max_rows_per_partition: int
    value_kind: str
    skew: float | None
    estimated: bool
    reasons: list[str]
    warnings: list[str]
    granularity_option: GranularityOptionSchema | None


class ExcludedColumnSchema(BaseModel):
    name: str
    reasons: list[str]


class PartitioningAdviceResponse(BaseModel):
    relation: RelationKeyStatsSchema
    statistics: list[KeyColumnStatsSchema]
    sizing: PartitionSizingSchema
    recommendations: list[PartitionRecommendationSchema]
    excluded: list[ExcludedColumnSchema]
    warnings: list[str]
    elapsed_ms: int
