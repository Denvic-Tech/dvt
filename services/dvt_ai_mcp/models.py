from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
