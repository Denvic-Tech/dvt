from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewNodeReference(StrictModel):
    ref: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"\S",
        description="Temporary node reference scoped to this patch; never persisted.",
    )


class ExistingNodeReference(StrictModel):
    id: str = Field(min_length=1, max_length=255)


NodeReference = NewNodeReference | ExistingNodeReference


class InputValueSchema(StrictModel):
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


class AddNodeSchema(StrictModel):
    ref: str = Field(
        min_length=1,
        max_length=255,
        pattern=r"\S",
        description="Unique temporary reference within this patch. Server assigns ID.",
    )
    node_type: str = Field(min_length=1)
    display_name: str | None = None
    comment: str | None = Field(default=None, max_length=20480)
    subgraph_id: str | None = None
    inputs: dict[str, InputValueSchema | None] = Field(
        default_factory=dict,
        description=(
            "Initial node inputs. Read get_node_definition for the schema, input "
            "agent_description guidance and node documentation before configuring them. "
            "Supply connection object inputs through add_connections from compatible outputs."
        ),
    )
    store_enabled: bool = False


class UpdateNodeSchema(StrictModel):
    id: str
    node_type: str | None = None
    display_name: str | None = None
    comment: str | None = Field(default=None, max_length=20480)
    subgraph_id: str | None = None
    inputs: dict[str, InputValueSchema | None] | None = Field(
        default=None,
        description=(
            "Only inputs that must change. Omitted keys keep their current value; a null entry "
            "removes the value. Follow input agent_description guidance and node documentation "
            "when reassessing affected settings. Never replace a connection edge by writing a "
            "connection ID into a consumer connection object input."
        ),
    )
    store_enabled: bool | None = None


class AddConnectionSchema(StrictModel):
    source: NodeReference
    source_output: str
    target: NodeReference
    target_input: str
    subgraph_id: str | None = None


class GraphPatchSchema(StrictModel):
    add_nodes: list[AddNodeSchema] = Field(default_factory=list)
    update_nodes: list[UpdateNodeSchema] = Field(default_factory=list)
    delete_node_ids: list[str] = Field(default_factory=list)
    add_connections: list[AddConnectionSchema] = Field(default_factory=list)
    delete_connection_ids: list[str] = Field(default_factory=list)
