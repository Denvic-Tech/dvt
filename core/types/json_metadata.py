from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JSONNodeKind(str, Enum):
    OBJECT = "OBJECT"
    ARRAY = "ARRAY"
    STRING = "STRING"
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    NULL = "NULL"
    UNION = "UNION"
    UNKNOWN = "UNKNOWN"


class JSONFlattenCandidateKind(str, Enum):
    RECORD_PATH = "RECORD_PATH"
    META_PATH = "META_PATH"
    EXPLODE_PATH = "EXPLODE_PATH"


class JSONFlattenCandidate(BaseModel):
    path: str = Field(description="Machine-readable JSON path.")
    display_path: str = Field(description="Human-readable JSON path.")
    kind: JSONFlattenCandidateKind = Field(description="Flatten candidate kind.")
    node_kind: JSONNodeKind = Field(description="Observed node kind for the candidate path.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Heuristic confidence score.")
    reason: str = Field(default="", description="Explanation of why the candidate was inferred.")


class JSONStructureNode(BaseModel):
    name: str = Field(description="Node name. For array items uses '[]', root uses '$'.")
    path: str = Field(description="Machine-readable JSON path.")
    display_path: str = Field(description="Human-readable JSON path.")
    kind: JSONNodeKind = Field(description="Effective JSON node kind.")
    required: bool = Field(default=True, description="Whether the node is present in every sampled parent.")
    nullable: bool = Field(default=False, description="Whether null was observed for this path.")
    occurrences: int = Field(default=0, ge=0, description="How many sampled observations reached this node.")
    kinds: list[JSONNodeKind] = Field(
        default_factory=list,
        description="Observed non-null kinds when the node is a UNION.",
    )
    object_keys: list[str] = Field(
        default_factory=list,
        description="Observed object keys for OBJECT nodes.",
    )
    children: list["JSONStructureNode"] = Field(
        default_factory=list,
        description="Child nodes for OBJECT and ARRAY nodes.",
    )
    item_kind: JSONNodeKind | None = Field(
        default=None,
        description="Observed item kind for ARRAY nodes.",
    )
    array_min_items: int | None = Field(
        default=None,
        ge=0,
        description="Minimum observed array size.",
    )
    array_max_items: int | None = Field(
        default=None,
        ge=0,
        description="Maximum observed array size.",
    )
    sampled_items: int | None = Field(
        default=None,
        ge=0,
        description="How many array items were sampled for structure inference.",
    )
    examples: list[Any] = Field(
        default_factory=list,
        description="Sample values for scalar nodes.",
    )


class JSONStructureStats(BaseModel):
    total_nodes: int = Field(default=0, ge=0)
    object_nodes: int = Field(default=0, ge=0)
    array_nodes: int = Field(default=0, ge=0)
    scalar_nodes: int = Field(default=0, ge=0)
    union_nodes: int = Field(default=0, ge=0)
    max_depth: int = Field(default=0, ge=0)


JSONStructureNode.model_rebuild()
