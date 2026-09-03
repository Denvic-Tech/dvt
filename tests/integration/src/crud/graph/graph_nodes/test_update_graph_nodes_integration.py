import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from usrak.core.security import hash_password

from src.crud.graph.graph_nodes.update import update_graph_nodes
from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.pipeline_graph.infra.db_models import GraphNodeRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord

pytestmark = [pytest.mark.asyncio, pytest.mark.docker_required]

async def test_update_graph_nodes_does_not_fail_on_store_enabled_coalesce(postgres_container) -> None:
    engine = create_async_engine(postgres_container.get_connection_url())

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        organization = OrganizationRecord(name="Integration org")
        session.add(organization)
        await session.commit()
        await session.refresh(organization)

        user = UserRecord(
            email="integration_user@email.com",
            hashed_password=hash_password("IntegrationUser123"),
            auth_provider="email",
            is_verified=True,
            is_active=True,
            role=DVTDefaultRoles.USER.value,
            organization_id=organization.id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        project = ProjectRecord(
            name="Integration Project",
            user_id=user.id,
            organization_id=organization.id,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)

        node = GraphNodeRecord(
            ui_id="node_integration_1",
            type="TestNode",
            position_x=1.0,
            position_y=2.0,
            selected=False,
            name="node",
            display_name="Node",
            comment=None,
            input_values={"x": {"__dvt_type": "const", "value": 1}},
            store_enabled=False,
            project_id=project.id,
            user_id=user.id,
            organization_id=organization.id,
        )
        session.add(node)
        await session.commit()
        await session.refresh(node)

        # Patch only a subset of fields (store_enabled omitted) - this previously could crash
        # with `COALESCE types text and boolean cannot be matched`.
        patch = GraphNodeRecord(
            id=node.id,
            ui_id=node.ui_id,
            project_id=project.id,
            user_id=user.id,
            organization_id=organization.id,
            selected=False,
            input_values={
                "connection_id": {
                    "__dvt_type": "const",
                    "value": "d4de8a2f-86a8-44ce-9f1a-acde00000000",
                }
            },
        )

        res = await update_graph_nodes(session=session, nodes=[patch])
        await session.commit()

        assert res

        # `expire_on_commit=False` in the sessionmaker means ORM objects can be stale after a
        # SQLAlchemy Core UPDATE, so explicitly refresh to validate DB state.
        await session.refresh(node)

        assert node.input_values.get("connection_id") == {
            "__dvt_type": "const",
            "value": "d4de8a2f-86a8-44ce-9f1a-acde00000000",
        }
        assert node.store_enabled is False

    await engine.dispose()
