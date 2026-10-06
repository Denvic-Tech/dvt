"""Scoped graph reads and concurrency tokens."""

import hashlib
import json
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from src.crud import graph as graph_crud
from src.modules.pipeline_graph.infra.db_models import (
    GraphEdgeRecord,
    GraphNodeRecord,
    SubgraphRecord,
)
from src.modules.pipeline_graph.infra.mappers import (
    graph_edges as graph_edges_dto,
    graph_nodes as graph_nodes_dto,
    subgraphs as subgraphs_dto,
)
from src.modules.project.infra.db_models import ProjectRecord

from ..errors import AIMCPHTTPError
from .mappers import edge_from_ui, node_from_ui, subgraph_from_ui
from .state import GraphSnapshot, GraphState


def compute_graph_etag(
    nodes: Sequence[GraphNodeRecord],
    edges: Sequence[GraphEdgeRecord],
    subgraphs: Sequence[SubgraphRecord],
) -> str:
    payload = {
        "nodes": sorted(
            [graph_nodes_dto.to_ui(node).model_dump(mode="json") for node in nodes],
            key=lambda item: item["id"],
        ),
        "edges": sorted(
            [graph_edges_dto.to_ui(edge).model_dump(mode="json") for edge in edges],
            key=lambda item: item["id"],
        ),
        "subgraphs": sorted(
            [subgraphs_dto.to_ui(item).model_dump(mode="json") for item in subgraphs],
            key=lambda item: item["id"],
        ),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def load_snapshot(
    session: AsyncSession,
    project: ProjectRecord,
    *,
    populate_existing: bool = False,
) -> GraphSnapshot:
    nodes, edges, groups = await graph_crud.get_graph_by(
        session,
        organization_id=project.organization_id,
        owner_user_id=project.user_id,
        project_id=project.id,
        populate_existing=populate_existing,
    )
    nodes, edges, groups = list(nodes), list(edges), list(groups)
    return GraphSnapshot(
        state=GraphState(
            nodes={node.ui_id: node_from_ui(graph_nodes_dto.to_ui(node)) for node in nodes},
            edges={edge.ui_id: edge_from_ui(graph_edges_dto.to_ui(edge)) for edge in edges},
            subgraphs={
                group.ui_id: subgraph_from_ui(subgraphs_dto.to_ui(group)) for group in groups
            },
        ),
        etag=compute_graph_etag(nodes, edges, groups),
    )


def check_graph_version(
    project: ProjectRecord,
    snapshot: GraphSnapshot,
    revision: int,
    etag: str,
) -> None:
    if project.graph_revision != revision:
        raise AIMCPHTTPError(409, "GRAPH_REVISION_CONFLICT", "Graph revision has changed.")
    if snapshot.etag != etag:
        raise AIMCPHTTPError(409, "GRAPH_ETAG_CONFLICT", "Graph content has changed.")
