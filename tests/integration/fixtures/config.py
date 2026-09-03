from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from usrak import AppConfig, RouterConfig

from src.models.user_tokens import UsersTokenRecord
from src.modules.user.infra.db_models import UserRecord as UserModel
from src.schemas.http.user import UserReadSchema
from src.schemas.http.users_tokens import UserTokenRead

from .settings import IntegrationTestSettings, integration_test_settings


@pytest.fixture(scope="session")
def app_config(
    test_db_url,
    integration_test_settings: IntegrationTestSettings,
) -> AppConfig:
    return AppConfig(
        DATABASE_URL=test_db_url,
        ALLOW_ORIGINS=["http://testgateway"],

        COOKIE_SECURE=False,  # Для тестов можно использовать небезопасные куки

        JWT_ACCESS_TOKEN_SECRET_KEY="test_access_secret",
        JWT_REFRESH_TOKEN_SECRET_KEY="test_refresh_secret",
        JWT_ONETIME_TOKEN_SECRET_KEY="test_onetime_secret",
        JWT_API_TOKEN_SECRET_KEY="test_api_secret",
        CODE_HASH_SALT="test_salt",
        FERNET_KEY=integration_test_settings.fernet_key,
        SMTP_SENDER_EMAIL="test@example.com",
        LMDB_PATH=str(integration_test_settings.lmdb_path),
    )


@pytest.fixture(scope="session")
def router_config(app_config) -> RouterConfig:
    return RouterConfig(
        USER_MODEL=UserModel,
        USER_READ_SCHEMA=UserReadSchema,
        TOKENS_MODEL=UsersTokenRecord,
        TOKENS_READ_SCHEMA=UserTokenRead,
    )


@pytest.fixture(scope="session")
def fernet_key_test(integration_test_settings: IntegrationTestSettings) -> str:
    return integration_test_settings.fernet_key

