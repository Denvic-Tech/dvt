from __future__ import annotations

import pytest

from src.modules.pipeline_graph.infra.db_models import (
    GraphEdgeRecord,
    GraphNodeRecord,
    SubgraphRecord,
)


@pytest.mark.asyncio
async def test_get_graph_returns_nodes_edges_and_subgraphs(
    gateway_client,
    router_prefix,
    db_session,
    test_user,
    test_user_project,
):
    subgraph = SubgraphRecord(
        ui_id="sub-1",
        type="subgraph",
        position_x=1.0,
        position_y=2.0,
        selected=False,
        name="Sub",
        display_name="Sub",
        comment=None,
        project_id=test_user_project.id,
        user_id=test_user.id,
        organization_id=test_user.organization_id,
    )
    db_session.add(subgraph)

    node_1 = GraphNodeRecord(
        ui_id="node-1",
        type="simpleinputnode",
        position_x=10.0,
        position_y=20.0,
        selected=False,
        name="Node1",
        display_name="Node1",
        comment=None,
        input_values={"value_in": {"__dvt_type": "const", "value": "hello"}},
        project_id=test_user_project.id,
        user_id=test_user.id,
        subgraph_id="sub-1",
        organization_id=test_user.organization_id,
    )
    node_2 = GraphNodeRecord(
        ui_id="node-2",
        type="simpleoutputnode",
        position_x=30.0,
        position_y=40.0,
        selected=False,
        name="Node2",
        display_name="Node2",
        comment=None,
        input_values={},
        project_id=test_user_project.id,
        user_id=test_user.id,
        subgraph_id="sub-1",
        organization_id=test_user.organization_id,
    )
    db_session.add(node_1)
    db_session.add(node_2)

    edge = GraphEdgeRecord(
        ui_id="edge-1",
        type="default",
        source="node-1",
        source_handle="output-out",
        target="node-2",
        target_handle="input-in",
        project_id=test_user_project.id,
        user_id=test_user.id,
        subgraph_id="sub-1",
        organization_id=test_user.organization_id,
    )
    db_session.add(edge)
    db_session.commit()

    response = await gateway_client.get(
        f"{router_prefix}/projects/{test_user_project.id}/graph"
    )

    assert response.status_code == 200
    nodes, edges, subgraphs = response.json()
    assert len(nodes) == 2
    assert len(edges) == 1
    assert len(subgraphs) == 1
