from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.data_catalog.domain import NodeColumnAnnotation
from src.modules.data_catalog.infra import SQLAlchemyNodeColumnAnnotationRepository
from src.modules.data_catalog.infra.db_models import NodeColumnAnnotationRecord
from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.modules.project.infra.db_models import ProjectRecord
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
    session.add(ProjectRecord(id="p1", name="P1", user_id=user.id, organization_id=organization.id))
    await session.flush()
    for ui_id in ("n1", "n2"):
        session.add(
            GraphNodeRecord(
                ui_id=ui_id, type="custom", position_x=0, position_y=0, name="DataFrameFilter", display_name=ui_id,
                project_id="p1", organization_id=organization.id, user_id=user.id,
            )
        )
    await session.flush()
    return organization.id, user.id


def _annotation(annotation_id: str, node_id: str, column: str, text: str) -> NodeColumnAnnotation:
    return NodeColumnAnnotation(
        id=annotation_id, project_id="p1", node_id=node_id, port="output", column=column, description=text,
        created_at=NOW, updated_at=NOW, origin_key=f"node:{node_id}:output:{column}", description_updated_by="u",
    )


@pytest.mark.asyncio
async def test_upsert_list_and_delete_round_trip(async_test_db_session):
    await _seed(async_test_db_session)
    repo = SQLAlchemyNodeColumnAnnotationRepository(async_test_db_session)

    await repo.upsert_many([_annotation("a2", "n2", "b", "B"), _annotation("a1", "n1", "a", "A")])
    listed = await repo.list_for_project("p1")
    assert [(item.node_id, item.column, item.description) for item in listed] == [("n1", "a", "A"), ("n2", "b", "B")]
    assert listed[0].ref.key == "node:n1:output:a" and listed[0].updated_at == NOW

    edited = listed[0]
    edited.description = "A2"
    edited.description_updated_by = "u2"
    await repo.upsert_many([edited])
    first = (await repo.list_for_project("p1"))[0]
    assert (first.id, first.description, first.description_updated_by) == ("a1", "A2", "u2")

    await repo.delete_many(["a1", "missing"])
    assert [item.id for item in await repo.list_for_project("p1")] == ["a2"]
    assert await repo.list_for_project("p-none") == []


@pytest.mark.asyncio
async def test_annotations_disappear_with_their_node(async_test_db_session):
    await _seed(async_test_db_session)
    repo = SQLAlchemyNodeColumnAnnotationRepository(async_test_db_session)
    await repo.upsert_many([_annotation("a1", "n1", "a", "A"), _annotation("a2", "n2", "b", "B")])

    await async_test_db_session.execute(
        sa.delete(GraphNodeRecord).where(GraphNodeRecord.project_id == "p1", GraphNodeRecord.ui_id == "n1")
    )
    await async_test_db_session.flush()

    remaining = (
        await async_test_db_session.execute(sa.select(NodeColumnAnnotationRecord.node_id))
    ).scalars().all()
    assert remaining == ["n2"], "FK ON DELETE CASCADE removes annotations of the deleted node"
