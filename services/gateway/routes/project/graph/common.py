from typing import Annotated

from fastapi import APIRouter, Path

from src.crud import graph as graph_crud
from src.db.fastapi.dependencies import AsyncSessionDepends
from src.modules.pipeline_graph.infra.mappers import (
    graph_edges as graph_edges_dto,
    graph_nodes as graph_nodes_dto,
    subgraphs as subgraphs_dto,
)
from src.modules.pipeline_graph.infra.schemas import GraphEdgeUISchema, GraphNodeUISchema, SubgraphUISchema
from src.modules.user.infra.fastapi.dependencies import UserAccessOnly
from src.utils.access_control import get_access_scope

router = r = APIRouter(tags=["Graph"])


@r.get("")
async def get_graph(
        project_id: Annotated[str, Path(description="ID проекта, для которого получить все edges")],
        session: AsyncSessionDepends,
        user: UserAccessOnly,
) -> tuple[list[GraphNodeUISchema], list[GraphEdgeUISchema], list[SubgraphUISchema]]:
    access_scope = get_access_scope(user)
    graph_nodes, graph_edges, subgraphs = await graph_crud.get_graph_by(
        session,
        organization_id=access_scope.organization_id,
        owner_user_id=access_scope.owner_user_id,
        project_id=project_id,
    )
    ui_nodes = [
        graph_nodes_dto.to_ui(graph_node)
        for graph_node in graph_nodes
    ]
    ui_edges = [
        graph_edges_dto.to_ui(graph_edge)
        for graph_edge in graph_edges
    ]
    ui_subgraphs = [
        subgraphs_dto.to_ui(subgraph)
        for subgraph in subgraphs
    ]
    return ui_nodes, ui_edges, ui_subgraphs
