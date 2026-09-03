import pytest

from .fixtures.db import (
    test_db_engine,
    test_db_session,
    async_test_db_engine,
    async_test_db_session
)

from .fixtures.user import (
    test_user_email,
    test_user_password,
    other_user_email,
    other_user_password,
    test_organization,
    test_organization_supuradmin,
    test_delete_organization,
    test_superadmin_user,
    test_admin_user,
    test_user,
)

from .fixtures.project import (
    test_admin_project,
    test_user_project
)

from .fixtures.queue_topic import (
    queue_topic_columns,
    test_queue_topic,
    other_queue_topic,
)


@pytest.fixture(scope="function")
def mock_regular_user(test_user):
    return test_user
