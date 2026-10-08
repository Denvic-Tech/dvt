"""Owned in-memory graph state; no database, transport, or layout side effects."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.node_dsl.core.input_values import NodeInputValues


@dataclass(frozen=True)
class Position:
    x: float
    y: float

    def mapping(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y}


@dataclass
class NodeState:
    id: str
    position: Position | None = None
    subgraph_id: str | None = None
    node_type: str = ""
    display_name: str = ""
    comment: str | None = None
    inputs: NodeInputValues = field(default_factory=dict)
    ui_type: str = "custom"
    selected: bool = False
    store_enabled: bool | None = False
    show_signal_io: bool | None = False
    show_variables_io: bool | None = False


@dataclass
class EdgeState:
    id: str
    source: str
    target: str
    source_handle: str = ""
    target_handle: str = ""
    subgraph_id: str | None = None
    ui_type: str = "custom"

    @property
    def target_input(self) -> str:
        return self.target_handle.removeprefix("input-")

    @property
    def source_output(self) -> str:
        return self.source_handle.removeprefix("output-")


@dataclass
class SubgraphState:
    id: str
    position: Position
    expanded: bool = True
    name: str = ""
    display_name: str = ""
    color: str | None = None
    comment: str | None = None
    ui_type: str = "subgraph"
    selected: bool = False


@dataclass
class GraphState:
    nodes: dict[str, NodeState] = field(default_factory=dict)
    edges: dict[str, EdgeState] = field(default_factory=dict)
    subgraphs: dict[str, SubgraphState] = field(default_factory=dict)

    def working_copy(self) -> GraphState:
        # Input constants may contain mutable JSON; a shallow copy is insufficient.
        return deepcopy(self)


@dataclass(frozen=True)
class GraphSnapshot:
    """Read-only by ownership: preparation always operates on working_copy()."""

    state: GraphState
    etag: str


@dataclass
class GraphChanges:
    created_node_ids: set[str] = field(default_factory=set)
    updated_node_ids: set[str] = field(default_factory=set)
    deleted_node_ids: set[str] = field(default_factory=set)
    created_edge_ids: set[str] = field(default_factory=set)
    deleted_edge_ids: set[str] = field(default_factory=set)
    touched_code_node_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class PositionChanges:
    nodes: dict[str, Position]
    subgraphs: dict[str, Position]

    @property
    def count(self) -> int:
        return len(self.nodes) + len(self.subgraphs)
