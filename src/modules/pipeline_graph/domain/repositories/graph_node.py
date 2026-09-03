from typing import Protocol

from ..entities import GraphNode


class GraphNodeRepository(Protocol):
    async def create(self, graph_node: GraphNode) -> GraphNode: ...

    async def update(self, graph_node: GraphNode) -> GraphNode: ...

    async def delete(self, graph_node: GraphNode) -> GraphNode: ...
