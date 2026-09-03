from typing import Protocol


class NodeRegistry(Protocol):
    def contains(self, node_name: str) -> bool: ...
