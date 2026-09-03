from __future__ import annotations

import warnings
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.crud.graph.common import get_graph_by
from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.node_dsl.core.input_values import NodeInputConstantValue


@pytest.mark.asyncio
async def test_get_graph_by_normalizes_input_values_without_serializer_warnings():
    raw_node = GraphNodeRecord(
        id="node-db-id-1",
        ui_id="node-ui-id-1",
        type="test-node",
        position_x=1.0,
        position_y=2.0,
        selected=False,
        name="TestNode",
        display_name="Test Node",
        input_values={
            "value_in": {
                "dvt_type": "const",
                "value": "hello",
            }
        },
        project_id="project-1",
        organization_id="org-1",
        user_id="user-1",
    )

    nodes_result = MagicMock()
    nodes_result.scalars.return_value = [raw_node]

    edges_result = MagicMock()
    edges_result.scalars.return_value = []

    subgraphs_result = MagicMock()
    subgraphs_result.scalars.return_value = []

    session = MagicMock()
    session.execute = AsyncMock(side_effect=[nodes_result, edges_result, subgraphs_result])

    with warnings.catch_warnings(record=True) as captured_warnings:
        warnings.simplefilter("always")
        graph_nodes, graph_edges, subgraphs = await get_graph_by(
            session=session,
            organization_id="org-1",
            owner_user_id="user-1",
            project_id="project-1",
        )

    assert len(graph_nodes) == 1
    assert isinstance(graph_nodes[0].input_values["value_in"], NodeInputConstantValue)
    assert graph_nodes[0].input_values["value_in"].value == "hello"
    assert graph_edges == []
    assert subgraphs == []
    assert captured_warnings == []
