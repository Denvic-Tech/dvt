from dataclasses import dataclass


@dataclass(frozen=True)
class GraphNodeID:
    value: str


@dataclass(frozen=True)
class GraphEdgeID:
    value: str


@dataclass(frozen=True)
class SubgraphID:
    value: str
