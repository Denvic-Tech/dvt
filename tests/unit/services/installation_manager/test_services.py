import pytest

from services.installation_manager.domain.models import InstallConfig
from services.installation_manager.domain.services import (
    AUTH_SECRET_FIELDS,
    parse_bool_value,
    parse_env_file,
    populate_install_auth_secrets,
    render_env_file,
    resolve_auth_secrets,
    update_ai_mcp_profile,
    validate_ai_mcp_secret,
)


def test_auth_secrets_are_generated_independently() -> None:
    resolved = resolve_auth_secrets({})

    assert set(resolved) == {env_name for _, env_name in AUTH_SECRET_FIELDS}
    assert all(len(value) >= 32 for value in resolved.values())
    assert len(set(resolved.values())) == len(AUTH_SECRET_FIELDS)


def test_install_auth_secrets_preserve_existing_values() -> None:
    existing = {
        env_name: f"existing-{index}-" + "x" * 32
        for index, (_, env_name) in enumerate(AUTH_SECRET_FIELDS)
    }
    cfg = InstallConfig()

    populate_install_auth_secrets(cfg, existing)

    for field_name, env_name in AUTH_SECRET_FIELDS:
        assert getattr(cfg, field_name) == existing[env_name]


def test_render_env_file_includes_celery_visibility_timeout() -> None:
    cfg = InstallConfig(
        ai_mcp_internal_secret="generated-internal-secret",
    )
    populate_install_auth_secrets(cfg, {})
    content = render_env_file(cfg)

    parsed = parse_env_file(content)
    assert parsed["DVT_CELERY_VISIBILITY_TIMEOUT_SEC"] == "28800"
    assert parsed["DVT_AI_MCP_ENABLED"] == "false"
    assert parsed["COMPOSE_PROFILES"] == ""
    assert parsed["DVT_AI_MCP_INTERNAL_SECRET"] == "generated-internal-secret"
    assert all(parsed[env_name] for _, env_name in AUTH_SECRET_FIELDS)


def test_render_env_file_enables_ai_mcp_profile_explicitly() -> None:
    parsed = parse_env_file(
        render_env_file(
            InstallConfig(
                ai_mcp_enabled=True,
                ai_mcp_internal_secret="x" * 32,
            )
        )
    )

    assert parsed["DVT_AI_MCP_ENABLED"] == "true"
    assert parsed["COMPOSE_PROFILES"] == "ai-mcp"


def test_update_ai_mcp_profile_preserves_unrelated_profiles() -> None:
    assert update_ai_mcp_profile("debug,ai-mcp,metrics", enabled=False) == "debug,metrics"
    assert update_ai_mcp_profile("debug,metrics", enabled=True) == "debug,metrics,ai-mcp"


def test_parse_bool_value_defaults_to_disabled_and_rejects_unknown_value() -> None:
    assert parse_bool_value(None) is False
    assert parse_bool_value("") is False
    assert parse_bool_value("ON") is True
    with pytest.raises(ValueError, match="DVT_AI_MCP_ENABLED"):
        parse_bool_value("sometimes")


def test_ai_mcp_secret_is_optional_only_while_disabled() -> None:
    validate_ai_mcp_secret("", enabled=False)
    validate_ai_mcp_secret("short", enabled=False)
    with pytest.raises(ValueError, match="не менее 32"):
        validate_ai_mcp_secret("short", enabled=True)
