from usrak import (
    AppConfig,
    AuthApp,
    PersistentTokenTypeConfig,
    RouterConfig,
    TokenTypeManagement,
)
from usrak.core.config_schemas import UserManagementRuleSet

from src import enums
from src.models.user_tokens import UsersTokenRecord as UsersTokensModel
from src.modules.user.infra.db_models import UserRecord as UserModel
from src.schemas.http.user import UserReadSchema
from src.schemas.http.users_tokens import UserTokenRead as UserTokenReadSchema

import config

SUPERADMIN_ROLE = enums.DVTDefaultRoles.SUPERADMIN.value
ADMIN_ROLE = enums.DVTDefaultRoles.ADMIN.value
USERS_ROLE = enums.DVTDefaultRoles.USER.value


def create_auth_app():
    config.SECURITY.validate()
    return AuthApp(
        app_config=AppConfig(
            DATABASE_URL=config.POSTGRES.DATABASE_URL,
            COOKIE_SECURE=config.GATEWAY.GATEWAY_COOKIE_SECURE,
            JWT_ACCESS_TOKEN_SECRET_KEY=config.SECURITY.JWT_ACCESS_TOKEN_SECRET_KEY,
            JWT_REFRESH_TOKEN_SECRET_KEY=config.SECURITY.JWT_REFRESH_TOKEN_SECRET_KEY,
            JWT_ONETIME_TOKEN_SECRET_KEY=config.SECURITY.JWT_ONETIME_TOKEN_SECRET_KEY,
            JWT_API_TOKEN_SECRET_KEY=config.SECURITY.JWT_API_TOKEN_SECRET_KEY,
            ACCESS_TOKEN_EXPIRE_SEC=60 * 60 * 24,  # 24 hours
            CODE_HASH_SALT=config.SECURITY.CODE_HASH_SALT,
            FERNET_KEY=config.SECURITY.FERNET_KEY,
        ),
        router_config=RouterConfig(
            USER_MODEL=UserModel,
            USER_READ_SCHEMA=UserReadSchema,
            TOKENS_MODEL=UsersTokensModel,
            TOKENS_READ_SCHEMA=UserTokenReadSchema,
            TOKENS_OWNER_FIELD_NAME="user_id",
            TOKENS_OWNER_RELATION_FIELD_NAME="user",
            PERSISTENT_TOKEN_TYPES=(
                PersistentTokenTypeConfig(
                    token_type="api_token",
                    management=TokenTypeManagement.USRAK_API,
                ),
                PersistentTokenTypeConfig(
                    token_type="MCP",
                    management=TokenTypeManagement.APPLICATION,
                ),
            ),
            DEFAULT_ROLES_ENUM=enums.DVTDefaultRoles,
            DEFAULT_USER_MANAGEMENT_RULES={
                SUPERADMIN_ROLE: UserManagementRuleSet(
                    create={ADMIN_ROLE, USERS_ROLE},
                    update={ADMIN_ROLE, USERS_ROLE},
                    delete={ADMIN_ROLE, USERS_ROLE},
                ),
                ADMIN_ROLE: UserManagementRuleSet(
                    create={ADMIN_ROLE, USERS_ROLE},
                    update={USERS_ROLE},
                    delete={USERS_ROLE},
                ),
            },
        ),
    )
