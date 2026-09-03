from usrak import TokenTypeManagement
from usrak.core.dependencies.config_provider import get_app_config, get_router_config
from usrak.routes.tokens import get_user_api_tokens

from services.gateway.auth_app import create_auth_app

import config


def test_auth_app_declares_mcp_as_application_managed_token_type():
    auth_app = create_auth_app()
    router_config = get_router_config()

    policies = {
        policy.token_type: policy.management
        for policy in router_config.PERSISTENT_TOKEN_TYPES
    }
    assert policies == {
        "api_token": TokenTypeManagement.USRAK_API,
        "MCP": TokenTypeManagement.APPLICATION,
    }
    assert router_config.usrak_api_token_type == "api_token"

    app_config = get_app_config()
    assert app_config.JWT_ACCESS_TOKEN_SECRET_KEY == config.SECURITY.JWT_ACCESS_TOKEN_SECRET_KEY
    assert app_config.JWT_REFRESH_TOKEN_SECRET_KEY == config.SECURITY.JWT_REFRESH_TOKEN_SECRET_KEY
    assert app_config.JWT_ONETIME_TOKEN_SECRET_KEY == config.SECURITY.JWT_ONETIME_TOKEN_SECRET_KEY
    assert app_config.JWT_API_TOKEN_SECRET_KEY == config.SECURITY.JWT_API_TOKEN_SECRET_KEY
    assert app_config.CODE_HASH_SALT == config.SECURITY.CODE_HASH_SALT

    list_route = next(
        route
        for route in auth_app.routes
        if getattr(route, "path", None) == "/api-tokens"
        and getattr(route, "methods", set()) == {"GET"}
    )
    assert list_route.endpoint is get_user_api_tokens
