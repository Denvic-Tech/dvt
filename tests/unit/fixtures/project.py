import uuid

import pytest

from src.modules.project.infra.db_models import ProjectRecord


@pytest.fixture(scope="function")
def test_admin_project(test_db_session, test_admin_user) -> ProjectRecord:
    """Создает проект для тестового админ пользователя."""

    project = ProjectRecord(
        id=str(uuid.uuid4()),
        name="My Own Project",
        user_id=test_admin_user.id,
        organization_id=test_admin_user.organization_id,
    )
    test_db_session.add(project)
    test_db_session.commit()
    test_db_session.refresh(project)
    yield project


@pytest.fixture(scope="function")
def test_user_project(test_db_session, test_user) -> ProjectRecord:
    """Создает проект для тестового пользователя."""

    project = ProjectRecord(
        id=str(uuid.uuid4()),
        name="My Own Project",
        user_id=test_user.id,
        organization_id=test_user.organization_id,
    )
    test_db_session.add(project)
    test_db_session.commit()
    test_db_session.refresh(project)
    yield project
