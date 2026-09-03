from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from usrak.core.security import hash_password

from src.crud.project.project_variables import (
    bulk_update_variables,
    create_variable,
    delete_variable,
    get_variable,
    get_variables,
    set_variables,
    update_variable,
)
from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.project.infra.db_models import ProjectRecord
from src.modules.user.infra.db_models import UserRecord
from src.schemas.http.project_variable import (
    ProjectVariableCreate,
    ProjectVariablesBulkUpdate,
    ProjectVariableUpdate,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.docker_required]

async def test_project_variables_crud_async(postgres_container) -> None:
    engine = create_async_engine(postgres_container.get_connection_url())
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        organization = OrganizationRecord(name="Vars org")
        session.add(organization)
        await session.commit()
        await session.refresh(organization)

        user = UserRecord(
            email="vars_async@email.com",
            hashed_password=hash_password("VarsAsync123"),
            auth_provider="email",
            is_verified=True,
            is_active=True,
            role=DVTDefaultRoles.USER.value,
            organization_id=organization.id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        project = ProjectRecord(name="Async vars", user_id=user.id, organization_id=organization.id)
        session.add(project)
        await session.commit()
        await session.refresh(project)

        created = await create_variable(
            session,
            project.id,
            "key1",
            ProjectVariableCreate(type="STRING", value="v1"),
            user,
        )
        assert created.key == "key1"
        assert created.type == "STRING"
        assert created.value == "v1"

        read_one = await get_variable(session, project.id, "key1", user)
        assert read_one.value == "v1"

        updated = await update_variable(
            session,
            project.id,
            "key1",
            ProjectVariableUpdate(type="STRING", value="v2"),
            user,
        )
        assert updated.value == "v2"

        updated_many = await bulk_update_variables(
            session,
            project.id,
            ProjectVariablesBulkUpdate(
                variables={
                    "key2": {"type": "INT", "value": 2},
                    "key3": {"type": "BOOLEAN", "value": True},
                }
            ),
            user,
        )
        assert {item.key for item in updated_many} == {"key2", "key3"}

        replaced = await set_variables(
            session,
            project.id,
            {"only": {"type": "STRING", "value": "left"}},
            user,
        )
        assert len(replaced) == 1
        assert replaced[0].key == "only"
        assert replaced[0].type == "STRING"
        assert replaced[0].value == "left"

        all_vars = await get_variables(session, project.id, user)
        assert len(all_vars) == 1
        assert all_vars[0].key == "only"

        await create_variable(
            session,
            project.id,
            "to_delete",
            ProjectVariableCreate(type="STRING", value="x"),
            user,
        )
        await delete_variable(session, project.id, "to_delete", user)

    await engine.dispose()
