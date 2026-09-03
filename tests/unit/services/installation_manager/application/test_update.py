from unittest.mock import MagicMock

from services.installation_manager.application.update import UpdateUseCase
from services.installation_manager.domain.models import Job, JobKind, UpdateConfig
from services.installation_manager.domain.services import AUTH_SECRET_FIELDS, parse_env_file


def _use_case(library: MagicMock) -> UpdateUseCase:
    settings = MagicMock()
    settings.target_services = (
        "orchestrator",
        "gateway",
        "dvt-ai-mcp",
        "ui",
        "proxy",
    )
    return UpdateUseCase(
        settings=settings,
        docker=MagicMock(),
        library=library,
        jobs=MagicMock(),
    )


def test_disabled_ai_mcp_is_removed_from_update_targets() -> None:
    use_case = _use_case(MagicMock())

    assert use_case._effective_targets(False) == ["orchestrator", "gateway", "ui", "proxy"]
    assert "dvt-ai-mcp" in use_case._effective_targets(True)


def test_update_env_disables_profile_and_preserves_secret() -> None:
    library = MagicMock()
    library.read_env_text.return_value = "\n".join(
        [
            "DVT_VERSION=old",
            "DVT_AI_MCP_ENABLED=true",
            f"DVT_AI_MCP_INTERNAL_SECRET={'s' * 32}",
            "COMPOSE_PROFILES=debug,ai-mcp",
            "",
        ]
    )
    use_case = _use_case(library)
    job = Job(JobKind.UPDATE, [])

    use_case._update_env(
        job,
        UpdateConfig(
            version="new",
            ai_mcp_enabled=False,
            ai_mcp_internal_secret="s" * 32,
        ),
    )

    written = library.write_env_text.call_args.args[0]
    parsed = parse_env_file(written)
    assert parsed["DVT_VERSION"] == "new"
    assert parsed["DVT_AI_MCP_ENABLED"] == "false"
    assert parsed["DVT_AI_MCP_INTERNAL_SECRET"] == "s" * 32
    assert parsed["COMPOSE_PROFILES"] == "debug"
    assert all(parsed[env_name] for _, env_name in AUTH_SECRET_FIELDS)


def test_update_env_preserves_existing_auth_secrets() -> None:
    existing_auth = {
        env_name: f"existing-{index}-" + "x" * 32
        for index, (_, env_name) in enumerate(AUTH_SECRET_FIELDS)
    }
    library = MagicMock()
    library.read_env_text.return_value = "\n".join(
        ["DVT_VERSION=old", *(f"{key}={value}" for key, value in existing_auth.items()), ""]
    )
    use_case = _use_case(library)

    use_case._update_env(
        Job(JobKind.UPDATE, []),
        UpdateConfig(version="new", ai_mcp_enabled=False),
    )

    parsed = parse_env_file(library.write_env_text.call_args.args[0])
    assert {key: parsed[key] for key in existing_auth} == existing_auth
