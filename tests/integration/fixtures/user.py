from typing import Any, Generator

import pytest

from src.enums import DVTDefaultRoles
from src.models import OrganizationRecord
from src.modules.user.infra.db_models import UserRecord, UserRecord as UserModel


@pytest.fixture(scope="session")
def test_user_email() -> str:
    return "gateway_admin@email.com"


@pytest.fixture(scope="session")
def test_user_password() -> str:
    return "GatewayAdmin123"


@pytest.fixture(scope="session")
def other_user_email() -> str:
    return "other_user@email.com"


@pytest.fixture(scope="session")
def other_user_password() -> str:
    return "OtherUser123"


@pytest.fixture(scope="function")
def test_organization(test_db_session) -> OrganizationRecord:
    organization = OrganizationRecord(name="Integration organization")
    test_db_session.add(organization)
    test_db_session.commit()
    test_db_session.refresh(organization)
    return organization


@pytest.fixture(scope="function")
def test_admin_user(
        test_db_session,
        test_organization,
        test_user_email,
        test_user_password,
) -> Generator[UserRecord, Any, None]:
    """
    Создает основного тестового админ пользователя.
    """
    from usrak.core.security import hash_password

    user = UserModel(
        email=test_user_email,
        hashed_password=hash_password(test_user_password),
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.ADMIN.value,
        organization_id=test_organization.id,
    )
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    yield user


@pytest.fixture(scope="function")
def test_user(
        test_db_session,
        test_organization,
        other_user_email,
        other_user_password,
) -> Generator[UserRecord, Any, None]:
    """
    Создает обычного пользователя.
    """
    from usrak.core.security import hash_password

    user = UserModel(
        email=other_user_email,
        hashed_password=hash_password(other_user_password),
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.USER.value,
        organization_id=test_organization.id,
    )
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)

    yield user



@pytest.fixture(scope="function")
def test_dvt_organization(test_dvt_db_session) -> OrganizationRecord:
    organization = OrganizationRecord(name="Integration organization")
    test_dvt_db_session.add(organization)
    test_dvt_db_session.commit()
    test_dvt_db_session.refresh(organization)
    return organization


@pytest.fixture(scope="function")
def test_dvt_user(
        test_dvt_db_session,
        test_dvt_organization,
        other_user_email,
        other_user_password,
) -> Generator[UserRecord, Any, None]:
    """
    Создает обычного пользователя.
    """
    from usrak.core.security import hash_password

    user = UserModel(
        email=other_user_email,
        hashed_password=hash_password(other_user_password),
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.USER.value,
        organization_id=test_dvt_organization.id,
    )
    test_dvt_db_session.add(user)
    test_dvt_db_session.commit()
    test_dvt_db_session.refresh(user)

    yield user


@pytest.fixture(scope="function")
def test_dvt_admin_user(
        test_dvt_db_session,
        test_dvt_organization,
        test_user_email,
        test_user_password,
) -> Generator[UserRecord, Any, None]:
    """
    Создает основного тестового админ пользователя.
    """
    from usrak.core.security import hash_password

    user = UserModel(
        email=test_user_email,
        hashed_password=hash_password(test_user_password),
        auth_provider="email",
        is_verified=True,
        is_active=True,
        role=DVTDefaultRoles.ADMIN.value,
        organization_id=test_dvt_organization.id,
    )
    test_dvt_db_session.add(user)
    test_dvt_db_session.commit()
    test_dvt_db_session.refresh(user)

    yield user



