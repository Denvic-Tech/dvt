from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import NO_VALUE

from src.modules.pipeline_graph.infra.db_models import (
    GraphEdgeRecord,
    GraphNodeRecord,
    SubgraphRecord,
)


def _normalize_target_nodes(target_nodes: Sequence[str] | None = None) -> list[str]:
    normalized: list[str] = []
    for node_id in target_nodes or []:
        if node_id and node_id not in normalized:
            normalized.append(node_id)
    return normalized


def _normalize_graph_node(node: GraphNodeRecord) -> GraphNodeRecord:
    state_dict = node.__dict__
    payload = {}

    for column in GraphNodeRecord.__table__.columns:
        value = state_dict.get(column.name, NO_VALUE)
        if value is NO_VALUE:
            continue
        payload[column.name] = value

    return GraphNodeRecord.model_validate(payload)


async def get_graph_by(
    session: AsyncSession,
    organization_id: str | None = None,
    owner_user_id: str | None = None,
    project_id: str | None = None,
    target_nodes: Sequence[str] | None = None,
) -> tuple[Sequence[GraphNodeRecord], Sequence[GraphEdgeRecord], Sequence[SubgraphRecord]]:
    node_filters: list[sa.ColumnElement[bool]] = []
    edge_filters: list[sa.ColumnElement[bool]] = []
    subgraph_filters: list[sa.ColumnElement[bool]] = []

    if organization_id:
        node_filters.append(GraphNodeRecord.organization_id == organization_id)
        edge_filters.append(GraphEdgeRecord.organization_id == organization_id)
        subgraph_filters.append(SubgraphRecord.organization_id == organization_id)

    if owner_user_id:
        node_filters.append(GraphNodeRecord.user_id == owner_user_id)
        edge_filters.append(GraphEdgeRecord.user_id == owner_user_id)
        subgraph_filters.append(SubgraphRecord.user_id == owner_user_id)

    if project_id:
        node_filters.append(GraphNodeRecord.project_id == project_id)
        edge_filters.append(GraphEdgeRecord.project_id == project_id)
        subgraph_filters.append(SubgraphRecord.project_id == project_id)

    normalized_target_nodes = _normalize_target_nodes(target_nodes)
    selected_node_ids: set[str] | None = None
    if normalized_target_nodes:
        selected_node_ids = set(normalized_target_nodes)
        frontier = set(normalized_target_nodes)
        while frontier:
            stmt = sa.select(GraphEdgeRecord.source, GraphEdgeRecord.target).where(
                *edge_filters,
                GraphEdgeRecord.target.in_(frontier),
            )
            upstream_rows = (await session.execute(stmt)).all()
            next_frontier = {row[0] for row in upstream_rows if row[0] not in selected_node_ids}
            selected_node_ids.update(next_frontier)
            frontier = next_frontier

    if selected_node_ids is not None:
        node_filters.append(GraphNodeRecord.ui_id.in_(selected_node_ids))

    nodes_stmt = sa.select(GraphNodeRecord).where(*node_filters)
    nodes = list((await session.execute(nodes_stmt)).scalars())
    normalized_nodes = [
        _normalize_graph_node(node)
        for node in nodes
    ]

    if selected_node_ids is not None:
        edge_filters.append(GraphEdgeRecord.source.in_(selected_node_ids))
        edge_filters.append(GraphEdgeRecord.target.in_(selected_node_ids))

    edges_stmt = sa.select(GraphEdgeRecord).where(*edge_filters)
    edges = list((await session.execute(edges_stmt)).scalars())

    subgraphs_stmt = sa.select(SubgraphRecord).where(*subgraph_filters)
    subgraphs = list((await session.execute(subgraphs_stmt)).scalars())
    return normalized_nodes, edges, subgraphs
