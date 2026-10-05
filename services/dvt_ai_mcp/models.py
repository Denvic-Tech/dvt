from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Position(StrictModel):
    x: float
    y: float


class InputValue(StrictModel):
    kind: Literal["constant", "expression", "connection_ref"] = Field(
        description=(
            "Use connection_ref only for an input whose schema type is *_CONNECTION_ID. "
            "A consumer *_CONNECTION object input must be supplied by an edge from that node."
        )
    )
    value: Any | None = None
    expression_kind: Literal["single", "template"] = "single"
    connection_id: str | None = Field(
        default=None,
        description=(
            "Scoped connection ID for a connection node's connection_id input; never place it "
            "directly in a reader, writer, SQL, or storage node's connection object input."
        ),
    )


class AddNode(StrictModel):
    id: str = Field(min_length=1, max_length=255)
    node_type: str = Field(min_length=1)
    display_name: str | None = None
    comment: str | None = Field(default=None, max_length=20480)
    position: Position | None = None
    subgraph_id: str | None = None
    inputs: dict[str, InputValue | None] = Field(
        default_factory=dict,
        description=(
            "Initial node inputs. Read get_node_definition for the schema, input "
            "agent_description guidance and node documentation before configuring them. "
            "Supply connection object inputs through add_connections from compatible outputs."
        ),
    )
    store_enabled: bool = False


class UpdateNode(StrictModel):
    id: str
    node_type: str | None = None
    display_name: str | None = None
    comment: str | None = Field(default=None, max_length=20480)
    position: Position | None = None
    subgraph_id: str | None = None
    inputs: dict[str, InputValue | None] | None = Field(
        default=None,
        description=(
            "Only inputs that must change. Omitted keys keep their current value; a null entry "
            "removes the value. Follow input agent_description guidance and node documentation "
            "when reassessing affected settings. Never replace a connection edge by writing a "
            "connection ID into a consumer connection object input."
        ),
    )
    store_enabled: bool | None = None


class AddConnection(StrictModel):
    id: str | None = None
    source: str
    source_output: str
    target: str
    target_input: str
    subgraph_id: str | None = None


class GraphPatch(StrictModel):
    add_nodes: list[AddNode] = Field(default_factory=list)
    update_nodes: list[UpdateNode] = Field(default_factory=list)
    delete_node_ids: list[str] = Field(default_factory=list)
    add_connections: list[AddConnection] = Field(default_factory=list)
    delete_connection_ids: list[str] = Field(default_factory=list)


class SchedulePatch(StrictModel):
    """Only supplied settings change; null values and an empty patch are invalid."""

    cron: str | None = Field(default=None, min_length=1)
    force_exec: bool | None = None
    max_retries: int | None = Field(default=None, ge=0, le=10)
    retry_delay_seconds: int | None = Field(default=None, ge=1, le=86400)
    retry_backoff: Literal["fixed", "exponential"] | None = None
    retry_max_delay_seconds: int | None = Field(default=None, ge=1, le=86400)

    @model_validator(mode="after")
    def validate_patch(self):
        if not self.model_fields_set or any(
            getattr(self, name) is None for name in self.model_fields_set
        ):
            raise ValueError("Provide non-null schedule settings to change.")
        return self


class RuntimeVariable(StrictModel):
    type: Literal["STRING", "BOOLEAN", "INT", "FLOAT", "DATETIME", "TIMEDELTA", "JSON"]
    value: Any
    is_list_type: bool = False


class DDLColumn(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    dtype: Literal[
        "INT",
        "FLOAT",
        "STRING",
        "BOOLEAN",
        "DATETIME",
        "TIMEDELTA",
        "CATEGORY",
        "DICTIONARY",
        "OBJECT",
    ]
    nullable: bool = True


class TableCreateSpec(StrictModel):
    primary_key_cols: str | list[str] | None = None
    indexes: list[dict[str, Any]] | None = None
    foreign_keys: list[dict[str, Any]] | None = None
    clickhouse: dict[str, Any] | None = Field(
        default=None,
        description=(
            "ClickHouse engine options such as engine_name, order_by, partition_by, "
            "primary_key, and settings."
        ),
    )


ColumnDataType = Literal[
    "INT", "FLOAT", "STRING", "BOOLEAN", "DATETIME", "TIMEDELTA", "CATEGORY",
    "DICTIONARY", "OBJECT", "UNKNOWN", "BINARY", "LIST", "STRUCT",
]


class ArrowField(StrictModel):
    name: str
    nullable: bool = True
    type: ArrowType


class ArrowType(StrictModel):
    kind: Literal[
        "scalar", "timestamp", "duration", "decimal", "list", "large_list",
        "fixed_size_list", "struct", "fixed_size_binary",
    ]
    name: str | None = None
    unit: Literal["s", "ms", "us", "ns"] | None = None
    timezone: str | None = None
    precision: int | None = None
    scale: int | None = None
    size: int | None = None
    fields: list[ArrowField] = Field(default_factory=list)


class DTypeMetadata(StrictModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    class_name: str = Field(alias="class")
    origin: Literal["numpy", "pandas", "python"]
    arrow_type: ArrowType | None = None
    repr: str | None = None
    module: str | None = None
    kind: str | None = None
    itemsize: int | None = None
    is_extension: bool | None = None
    scalar_type: str | None = None
    storage: str | None = None
    unit: str | None = None
    timezone: str | None = None
    ordered: bool | None = None
    categories_count: int | None = None
    categories_dtype: str | None = None


class DataFrameColumn(StrictModel):
    name: str = Field(min_length=1)
    dtype: ColumnDataType
    nullable: bool | None = None
    comment: str | None = None
    dtype_metadata: DTypeMetadata | None = None
    index: bool | None = None


class DatabaseColumn(DataFrameColumn):
    indexes: list[str] | None = None
    primary_key: bool | None = None


class DataFrameMetadata(StrictModel):
    type: Literal["DATAFRAME"] = "DATAFRAME"
    columns: list[DataFrameColumn]
    comment: str | None = None
    rows_num: int | None = Field(default=None, ge=0)
    size: int | None = Field(default=None, ge=0)


class WriteColumnMapping(StrictModel):
    source_name: str = Field(min_length=1)
    target_name: str = Field(min_length=1)
    dtype: str | None = None
    nullable: bool | None = None


class TableColumnAction(StrictModel):
    type: Literal[
        "add_column", "drop_column", "recreate_column",
        "set_column_nullable", "set_column_comment",
    ] = Field(description=(
        "recreate_column drops and adds the column, losing its values; it is not a "
        "data-preserving type conversion. Drop/recreate require explicitly agreed data loss."
    ))
    column_name: str = Field(min_length=1)
    column: DatabaseColumn | None = None
    comment: str | None = Field(
        default=None, description="For set_column_comment, supply explicitly; null removes it."
    )
    nullable: StrictBool | None = Field(default=None, description=(
        "Explicit boolean for set_column_nullable. Preview does not scan for NULLs; "
        "apply checks existing NULLs before any DDL. Pause concurrent ClickHouse writes "
        "before setting nullable=false."
    ))

    @model_validator(mode="after")
    def validate_action(self):
        if not self.column_name.strip():
            raise ValueError("column_name must not be blank.")
        if self.type in {"add_column", "recreate_column"} and (
            self.column is None or self.column.name.strip() != self.column_name.strip()
        ):
            raise ValueError("Provide column with a name matching column_name.")
        if self.type == "set_column_comment" and (
            "comment" not in self.model_fields_set or self.column is not None
        ):
            raise ValueError("Provide comment explicitly and omit column.")
        if self.type == "set_column_nullable":
            if self.nullable is None or {"column", "comment"} & self.model_fields_set:
                raise ValueError("Provide nullable explicitly and omit column/comment.")
        elif self.nullable is not None:
            raise ValueError("nullable is only allowed for set_column_nullable.")
        return self
