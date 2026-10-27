from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.data_catalog.infra.db_models import NodeColumnAnnotationRecord
from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.project_transfer.domain.policies import remap_graph_snapshot
from src.modules.project_transfer.infra.graph_cloner import (
    delete_graph,
    insert_graph_snapshot,
    read_graph_snapshot,
)
from src.modules.user.infra.db_models import UserRecord

NOW = datetime(2026, 10, 21, tzinfo=UTC)


async def _seed(session) -> tuple[str, str]:
    organization = OrganizationRecord(name="Org")
    session.add(organization)
    await session.flush()
    user = UserRecord(
        email="owner@example.com", hashed_password="h", auth_provider="email", is_verified=True, is_active=True,
        role=DVTDefaultRoles.USER.value, organization_id=organization.id,
    )
    session.add(user)
    await session.flush()
    session.add_all(
        [
            ProjectRecord(id="src", name="Source", user_id=user.id, organization_id=organization.id),
            ProjectRecord(id="dst", name="Target", user_id=user.id, organization_id=organization.id),
        ]
    )
    await session.flush()
    session.add(
        GraphNodeRecord(
            ui_id="n1", type="custom", position_x=0, position_y=0, name="DataFrameFilter", display_name="F",
            project_id="src", organization_id=organization.id, user_id=user.id,
        )
    )
    await session.flush()
    session.add(
        NodeColumnAnnotationRecord(
            project_id="src", node_id="n1", port="output", column_name="score", description="Скоринг",
            origin_key="node:n1:output:score", description_updated_by="author", created_at=NOW, updated_at=NOW,
        )
    )
    await session.flush()
    return organization.id, user.id


@pytest.mark.asyncio
async def test_annotations_are_copied_with_the_graph_and_deleted_with_it(async_test_db_session):
    org_id, _ = await _seed(async_test_db_session)

    snapshot = await read_graph_snapshot(async_test_db_session, "src")
    assert [(a.node_ui_id, a.port, a.column, a.description, a.origin_key) for a in snapshot.column_annotations] == [
        ("n1", "output", "score", "Скоринг", "node:n1:output:score")
    ]

    remapped = remap_graph_snapshot(snapshot, organization_id=org_id, project_id="dst")
    await insert_graph_snapshot(
        async_test_db_session, remapped.snapshot, project_id="dst", user_id="copier", organization_id=org_id, now=NOW
    )

    rows = (
        await async_test_db_session.execute(
            sa.select(NodeColumnAnnotationRecord).where(NodeColumnAnnotationRecord.project_id == "dst")
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].node_id == remapped.mapping.nodes["n1"]
    assert (rows[0].column_name, rows[0].description) == ("score", "Скоринг")
    assert rows[0].origin_key is None and rows[0].description_updated_by == "copier"

    await delete_graph(async_test_db_session, "dst")
    left = (
        await async_test_db_session.execute(sa.select(NodeColumnAnnotationRecord.project_id))
    ).scalars().all()
    assert left == ["src"]
