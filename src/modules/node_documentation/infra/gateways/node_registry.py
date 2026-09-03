from src.node_dsl import get_all_nodes

from ...domain.gateways import NodeRegistry


class DSLNodeRegistry(NodeRegistry):
    def contains(self, node_name: str) -> bool:
        return node_name in get_all_nodes()
