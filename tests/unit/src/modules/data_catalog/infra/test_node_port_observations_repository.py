from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.data_catalog.domain import (
    LINEAGE_SCHEMA_VERSION,
    ObservedField,
    ObservedPortSchema,
    ProjectCatalogProjection,
    ProjectionStamp,
    ProjectionStatus,
)
from src.modules.data_catalog.infra import (
    SQLAlchemyNodePortObservationRepository,
    SQLAlchemyProjectionRepository,
)
from src.modules.data_catalog.infra.db_models import NodePortObservationRecord
from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord

NOW = datetime(2026, 10, 27, tzinfo=UTC)


async def _seed(session) -> str:
    organization = OrganizationRecord(name="Org")
    session.add(organization)
    await session.flush()
    user = UserRecord(
        email="owner@example.com", hashed_password="h", auth_provider="email", is_verified=True, is_active=True,
        role=DVTDefaultRoles.USER.value, organization_id=organization.id,
    )
    session.add(user)
    await session.flush()
    session.add(ProjectRecord(id="p1", name="P1", user_id=user.id, organization_id=organization.id))
    await session.flush()
    for ui_id in ("x", "y"):
        session.add(
            GraphNodeRecord(
                ui_id=ui_id, type="custom", position_x=0, position_y=0, name="DataFrameExecCode", display_name=ui_id,
                project_id="p1", organization_id=organization.id, user_id=user.id,
            )
        )
    await session.flush()
    return organization.id


def _observation(node_id: str, port: str, *names: str, revision: int = 1) -> ObservedPortSchema:
    return ObservedPortSchema(
        "p1", node_id, port, tuple(ObservedField(name, "INT", True, i) for i, name in enumerate(names, 1)),
        NOW, graph_revision=revision, task_id="t1",
    )


@pytest.mark.asyncio
async def test_upsert_is_keyed_by_project_node_and_port(async_test_db_session):
    await _seed(async_test_db_session)
    repo = SQLAlchemyNodePortObservationRepository(async_test_db_session)

    await repo.upsert_many([_observation("x", "output", "a", "b"), _observation("y", "output", "z")])
    await repo.upsert_many([_observation("x", "output", "a", "b", "c", revision=2)])

    stored = await repo.list_for_project("p1")
    assert [(item.node_id, item.port, item.names, item.graph_revision) for item in stored] == [
        ("x", "output", ("a", "b", "c"), 2),
        ("y", "output", ("z",), 1),
    ]
    assert stored[0].columns[0].dtype == "INT" and stored[0].observed_at == NOW
    assert [item.names for item in await repo.list_for_node("p1", "y")] == [("z",)]
    rows = (await async_test_db_session.execute(sa.select(sa.func.count()).select_from(NodePortObservationRecord))).scalar_one()
    assert rows == 2, "a repeated observation updates the row instead of adding one"


@pytest.mark.asyncio
async def test_observations_disappear_with_their_node_and_projection_can_be_marked_stale(async_test_db_session):
    org_id = await _seed(async_test_db_session)
    repo = SQLAlchemyNodePortObservationRepository(async_test_db_session)
    await repo.upsert_many([_observation("x", "output", "a"), _observation("y", "output", "z")])

    await async_test_db_session.execute(
        sa.delete(GraphNodeRecord).where(GraphNodeRecord.project_id == "p1", GraphNodeRecord.ui_id == "x")
    )
    await async_test_db_session.flush()
    assert [item.node_id for item in await repo.list_for_project("p1")] == ["y"]

    projections = SQLAlchemyProjectionRepository(async_test_db_session)
    await projections.save(
        ProjectCatalogProjection(
            project_id="p1", organization_id=org_id, stamp=ProjectionStamp(1, "fp", LINEAGE_SCHEMA_VERSION),
            built_at=NOW, status=ProjectionStatus.OK,
        )
    )
    assert await projections.mark_stale_for_project("p1") is True
    assert (await projections.get("p1")).stamp.lineage_schema_version == 0
    assert await projections.mark_stale_for_project("p1") is False, "already stale"
    assert await projections.mark_stale_for_project("missing") is False
