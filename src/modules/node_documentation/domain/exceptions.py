class NodeDocumentationError(Exception):
    """Base node documentation error."""


class UnknownNode(NodeDocumentationError):
    def __init__(self, node_name: str) -> None:
        super().__init__(f"Unknown node: {node_name}")


class NodeDocumentationNotFound(NodeDocumentationError):
    def __init__(self, node_name: str) -> None:
        super().__init__(f"Documentation not found for node: {node_name}")
