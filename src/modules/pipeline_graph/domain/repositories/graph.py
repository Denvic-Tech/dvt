from typing import Protocol

from ..entities import GraphEdge, GraphNode, Subgraph


class GraphRepository(Protocol):
    async def list(self) -> tuple[list[GraphNode], list[GraphEdge], list[Subgraph]]: ...