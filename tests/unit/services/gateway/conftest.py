import pytest

from .fixtures.config import (
    app_config,
    router_config,
)
from .fixtures.app import (
    router_prefix,
    auth_app,
    gateway_client,
    unauthenticated_gateway_client,
)


@pytest.fixture()
def db_session(test_db_session):
    return test_db_session


@pytest.fixture()
def async_db_session(async_test_db_session):
    return async_test_db_session
