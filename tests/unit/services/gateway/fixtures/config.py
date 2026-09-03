import os

os.environ["LOG_TO_DB"] = "false"

import pytest

from usrak import AppConfig, RouterConfig

from src.modules.user.infra.db_models import UserRecord as UserModel
from src.models.user_tokens import UsersTokenRecord
from src.schemas.http.user import UserReadSchema
from src.schemas.http.users_tokens import UserTokenRead


@pytest.fixture(scope="session")
def app_config() -> AppConfig:
    return AppConfig(
        DATABASE_URL="postgresql+psycopg://user:pass@localhost/test_db",
        ALLOW_ORIGINS=["http://testgateway"],

        COOKIE_SECURE=False,  # Для тестов можно использовать небезопасные куки

        JWT_ACCESS_TOKEN_SECRET_KEY="test_access_secret",
        JWT_REFRESH_TOKEN_SECRET_KEY="test_refresh_secret",
        JWT_ONETIME_TOKEN_SECRET_KEY="test_onetime_secret",
        JWT_API_TOKEN_SECRET_KEY="test_api_secret",
        CODE_HASH_SALT="test_salt",
        FERNET_KEY="Y8RFpaIxSaAFNsB352tpLXl5znUw5anEKIZgclOezak=",  # Ключ должен быть 32 байта base64
        SMTP_SENDER_EMAIL="test@example.com",
        LMDB_PATH="./test_usrak_lmdb_data",  # Используем временный путь или путь в build артефактах
    )


@pytest.fixture(scope="session")
def router_config(app_config) -> RouterConfig:
    return RouterConfig(
        USER_MODEL=UserModel,
        USER_READ_SCHEMA=UserReadSchema,
        TOKENS_MODEL=UsersTokenRecord,
        TOKENS_READ_SCHEMA=UserTokenRead,
    )
