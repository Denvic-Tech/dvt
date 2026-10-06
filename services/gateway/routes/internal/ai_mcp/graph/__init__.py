"""Public entrypoints for MCP graph operations."""

from .connections import analyze_graph_connection_dependencies
from .impl import (
    apply_graph_changes,
    auto_layout_project,
    get_project_graph,
    validate_graph_changes,
)
from .schemas import GraphPatchSchema
from .snapshot import compute_graph_etag

__all__ = [
    "GraphPatchSchema",
    "analyze_graph_connection_dependencies",
    "apply_graph_changes",
    "auto_layout_project",
    "compute_graph_etag",
    "get_project_graph",
    "validate_graph_changes",
]
