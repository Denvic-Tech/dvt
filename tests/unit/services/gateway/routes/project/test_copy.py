from __future__ import annotations

import pytest
import sqlalchemy as sa
from usrak.core.security import hash_password

from services.gateway.routes.project.copy import copy_project

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.file_storage.infra.db_models import DVTServiceFileObjectRecord
from src.modules.pipeline_graph.infra.db_models import (
    GraphEdgeRecord,
    GraphNodeRecord,
    SubgraphRecord,
)
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord
from src.schemas.http.project import ProjectUpdateSchema


@pytest.fixture
async def async_test_user(async_db_session) -> UserRecord:
    organization = OrganizationRecord(name="Async copy org")
    user = UserRecord(
        email="async-copy-user@example.com",
        hashed_password=hash_password("Password123"),
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.USER.value,
        organization_id=organization.id,
    )

    async_db_session.add(organization)
    async_db_session.add(user)
    await async_db_session.commit()
    await async_db_session.refresh(organization)
    await async_db_session.refresh(user)
    return user


@pytest.fixture
async def async_test_user_project(async_db_session, async_test_user: UserRecord) -> ProjectRecord:
    project = ProjectRecord(
        name="My Own Project",
        user_id=async_test_user.id,
        organization_id=async_test_user.organization_id,
    )

    async_db_session.add(project)
    await async_db_session.commit()
    await async_db_session.refresh(project)
    return project


@pytest.mark.asyncio
async def test_copy_project_relinks_edge_endpoints_to_copied_nodes(
    async_db_session,
    async_test_user: UserRecord,
    async_test_user_project: ProjectRecord,
):
    async_db_session.add(
        GraphNodeRecord(
            ui_id="node-source",
            type="simpleinputnode",
            position_x=10.0,
            position_y=20.0,
            selected=False,
            name="Source",
            display_name="Source",
            comment=None,
            input_values={},
            project_id=async_test_user_project.id,
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
        )
    )
    async_db_session.add(
        GraphNodeRecord(
            ui_id="node-target",
            type="simpleoutputnode",
            position_x=30.0,
            position_y=40.0,
            selected=False,
            name="Target",
            display_name="Target",
            comment=None,
            input_values={},
            project_id=async_test_user_project.id,
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
        )
    )
    async_db_session.add(
        GraphEdgeRecord(
            ui_id="edge-main",
            type="default",
            source="node-source",
            source_handle="output-out",
            target="node-target",
            target_handle="input-in",
            project_id=async_test_user_project.id,
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
        )
    )
    await async_db_session.commit()

    copied_project = await copy_project(
        project_id=async_test_user_project.id,
        data=ProjectUpdateSchema(),
        session=async_db_session,
        user=async_test_user,
        project=async_test_user_project,
    )

    copied_nodes = (
        await async_db_session.execute(
            sa.select(GraphNodeRecord).where(GraphNodeRecord.project_id == copied_project.id)
        )
    ).scalars().all()
    copied_edges = (
        await async_db_session.execute(
            sa.select(GraphEdgeRecord).where(GraphEdgeRecord.project_id == copied_project.id)
        )
    ).scalars().all()

    assert len(copied_nodes) == 2
    assert len(copied_edges) == 1
    assert copied_project.user_email == async_test_user.email

    copied_node_ids = {node.ui_id for node in copied_nodes}
    copied_edge = copied_edges[0]
    assert copied_edge.source in copied_node_ids
    assert copied_edge.target in copied_node_ids


@pytest.mark.asyncio
async def test_copy_project_relinks_multiple_edges_with_correct_direction(
    async_db_session,
    async_test_user: UserRecord,
    async_test_user_project: ProjectRecord,
):
    async_db_session.add(
        GraphNodeRecord(
            ui_id="node-a",
            type="simpleinputnode",
            position_x=1.0,
            position_y=1.0,
            selected=False,
            name="Node A",
            display_name="Node A",
            comment=None,
            input_values={},
            project_id=async_test_user_project.id,
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
        )
    )
    async_db_session.add(
        GraphNodeRecord(
            ui_id="node-b",
            type="middle",
            position_x=2.0,
            position_y=2.0,
            selected=False,
            name="Node B",
            display_name="Node B",
            comment=None,
            input_values={},
            project_id=async_test_user_project.id,
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
        )
    )
    async_db_session.add(
        GraphNodeRecord(
            ui_id="node-c",
            type="simpleoutputnode",
            position_x=3.0,
            position_y=3.0,
            selected=False,
            name="Node C",
            display_name="Node C",
            comment=None,
            input_values={},
            project_id=async_test_user_project.id,
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
        )
    )
    async_db_session.add(
        GraphEdgeRecord(
            ui_id="edge-ab",
            type="default",
            source="node-a",
            source_handle="out-a",
            target="node-b",
            target_handle="in-b",
            project_id=async_test_user_project.id,
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
        )
    )
    async_db_session.add(
        GraphEdgeRecord(
            ui_id="edge-bc",
            type="default",
            source="node-b",
            source_handle="out-b",
            target="node-c",
            target_handle="in-c",
            project_id=async_test_user_project.id,
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
        )
    )
    await async_db_session.commit()

    copied_project = await copy_project(
        project_id=async_test_user_project.id,
        data=ProjectUpdateSchema(),
        session=async_db_session,
        user=async_test_user,
        project=async_test_user_project,
    )

    copied_nodes = (
        await async_db_session.execute(
            sa.select(GraphNodeRecord).where(GraphNodeRecord.project_id == copied_project.id)
        )
    ).scalars().all()
    copied_edges = (
        await async_db_session.execute(
            sa.select(GraphEdgeRecord).where(GraphEdgeRecord.project_id == copied_project.id)
        )
    ).scalars().all()

    assert len(copied_nodes) == 3
    assert len(copied_edges) == 2

    node_id_by_name = {node.name: node.ui_id for node in copied_nodes}
    edge_by_handles = {
        (edge.source_handle, edge.target_handle): edge
        for edge in copied_edges
    }

    edge_ab = edge_by_handles[("out-a", "in-b")]
    assert edge_ab.source == node_id_by_name["Node A"]
    assert edge_ab.target == node_id_by_name["Node B"]

    edge_bc = edge_by_handles[("out-b", "in-c")]
    assert edge_bc.source == node_id_by_name["Node B"]
    assert edge_bc.target == node_id_by_name["Node C"]


@pytest.mark.asyncio
async def test_copy_project_copies_subgraphs_and_relinks_subgraph_ids(
    async_db_session,
    async_test_user: UserRecord,
    async_test_user_project: ProjectRecord,
):
    async_db_session.add(
        SubgraphRecord(
            ui_id="sub-1",
            type="subgraph",
            position_x=100.0,
            position_y=200.0,
            selected=False,
            expanded=True,
            name="SubgraphRecord 1",
            display_name="SubgraphRecord 1",
            comment="test",
            color="#112233",
            project_id=async_test_user_project.id,
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
        )
    )
    async_db_session.add(
        GraphNodeRecord(
            ui_id="sub-node-1",
            type="simpleinputnode",
            position_x=10.0,
            position_y=20.0,
            selected=False,
            name="Node 1",
            display_name="Node 1",
            comment=None,
            input_values={},
            subgraph_id="sub-1",
            project_id=async_test_user_project.id,
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
        )
    )
    async_db_session.add(
        GraphNodeRecord(
            ui_id="sub-node-2",
            type="simpleoutputnode",
            position_x=30.0,
            position_y=40.0,
            selected=False,
            name="Node 2",
            display_name="Node 2",
            comment=None,
            input_values={},
            subgraph_id="sub-1",
            project_id=async_test_user_project.id,
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
        )
    )
    async_db_session.add(
        GraphEdgeRecord(
            ui_id="sub-edge-1",
            type="default",
            source="sub-node-1",
            source_handle="out",
            target="sub-node-2",
            target_handle="in",
            subgraph_id="sub-1",
            project_id=async_test_user_project.id,
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
        )
    )
    await async_db_session.commit()

    copied_project = await copy_project(
        project_id=async_test_user_project.id,
        data=ProjectUpdateSchema(),
        session=async_db_session,
        user=async_test_user,
        project=async_test_user_project,
    )

    copied_subgraphs = (
        await async_db_session.execute(
            sa.select(SubgraphRecord).where(SubgraphRecord.project_id == copied_project.id)
        )
    ).scalars().all()
    copied_nodes = (
        await async_db_session.execute(
            sa.select(GraphNodeRecord).where(GraphNodeRecord.project_id == copied_project.id)
        )
    ).scalars().all()
    copied_edges = (
        await async_db_session.execute(
            sa.select(GraphEdgeRecord).where(GraphEdgeRecord.project_id == copied_project.id)
        )
    ).scalars().all()

    assert len(copied_subgraphs) == 1
    assert len(copied_nodes) == 2
    assert len(copied_edges) == 1

    copied_subgraph_ui_id = copied_subgraphs[0].ui_id
    assert copied_subgraph_ui_id != "sub-1"

    assert all(node.subgraph_id == copied_subgraph_ui_id for node in copied_nodes)
    assert copied_edges[0].subgraph_id == copied_subgraph_ui_id


@pytest.mark.asyncio
async def test_copy_project_copies_dvt_service_file_inputs(
    async_db_session,
    async_test_user: UserRecord,
    async_test_user_project: ProjectRecord,
):
    old_root_prefix = "node-inputs/node-source/file"
    async_db_session.add(
        GraphNodeRecord(
            ui_id="node-source",
            type="simpleinputnode",
            position_x=10.0,
            position_y=20.0,
            selected=False,
            name="LoadCSV",
            display_name="Load CSV",
            comment=None,
            input_values={
                "connection": {
                    "__dvt_type": "const",
                    "value": {
                        "id": "dvt-service-files:old-project:node-source:file",
                        "name": "DVT service files",
                        "kind": "file",
                        "type": "dvt_service_files",
                        "properties": {
                            "organization_id": async_test_user.organization_id,
                            "project_id": async_test_user_project.id,
                            "root_prefix": old_root_prefix,
                        },
                        "secrets": {},
                    },
                },
                "path": {"__dvt_type": "const", "value": "data.csv"},
            },
            project_id=async_test_user_project.id,
            user_id=async_test_user.id,
            organization_id=async_test_user.organization_id,
        )
    )
    async_db_session.add(
        DVTServiceFileObjectRecord(
            organization_id=async_test_user.organization_id,
            project_id=async_test_user_project.id,
            parent_path=old_root_prefix,
            name="data.csv",
            is_dir=False,
            content=b"id,name\n1,Alice\n",
            content_type="text/csv",
            size=16,
            sha256="digest",
        )
    )
    await async_db_session.commit()

    copied_project = await copy_project(
        project_id=async_test_user_project.id,
        data=ProjectUpdateSchema(),
        session=async_db_session,
        user=async_test_user,
        project=async_test_user_project,
    )

    copied_node = (
        await async_db_session.execute(
            sa.select(GraphNodeRecord).where(GraphNodeRecord.project_id == copied_project.id)
        )
    ).scalar_one()
    copied_connection = copied_node.input_values["connection"]["value"]
    copied_root_prefix = copied_connection["properties"]["root_prefix"]

    assert copied_connection["properties"]["project_id"] == copied_project.id
    assert copied_root_prefix.startswith(f"node-inputs/{copied_node.ui_id}/")
    assert copied_root_prefix != old_root_prefix

    copied_file = (
        await async_db_session.execute(
            sa.select(DVTServiceFileObjectRecord).where(
                DVTServiceFileObjectRecord.project_id == copied_project.id,
                DVTServiceFileObjectRecord.parent_path == copied_root_prefix,
                DVTServiceFileObjectRecord.name == "data.csv",
            )
        )
    ).scalar_one()
    assert copied_file.content == b"id,name\n1,Alice\n"
