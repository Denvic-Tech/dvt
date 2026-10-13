import pytest

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.data_catalog.infra import SQLConnectionLocatorGateway
from src.modules.data_catalog.infra.gateways import public_connection_properties
from src.modules.db_connection.infra.db_models import DVTStoredConnectionRecord
from src.modules.user.infra.db_models import UserRecord


def test_public_properties_drop_secret_like_keys_and_tolerate_non_dicts():
    properties = {
        "host": "db",
        "port": 5432,
        "database": "main",
        "password": "hunter2",
        "api_token": "t",
        "client_secret": "s",
        "ssh_key": "k",
        "credentials": {"user": "x"},
    }
    assert public_connection_properties(properties) == {"host": "db", "port": 5432, "database": "main"}
    assert public_connection_properties(None) == {}
    assert public_connection_properties("not-a-dict") == {}


@pytest.mark.asyncio
async def test_gateway_returns_type_revision_and_public_properties_only(async_test_db_session):
    session = async_test_db_session
    organization = OrganizationRecord(name="Org")
    session.add(organization)
    await session.flush()
    user = UserRecord(
        email="owner@example.com",
        hashed_password="h",
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.USER.value,
        organization_id=organization.id,
    )
    session.add(user)
    await session.flush()
    session.add(
        DVTStoredConnectionRecord(
            id="conn-1",
            name="pg",
            kind="sql",
            type="Postgres",
            properties_json={"host": "db", "port": 5432, "database": "main", "password": "x"},
            user_id=user.id,
            organization_id=organization.id,
        )
    )
    await session.flush()

    gateway = SQLConnectionLocatorGateway(session)
    locator = await gateway.get_locator("conn-1", organization.id)

    assert locator is not None
    assert locator.type == "postgres"
    assert locator.deleted is False
    assert locator.properties == {"host": "db", "port": 5432, "database": "main"}
    assert await gateway.get_locator("conn-1", "other-org") is None
