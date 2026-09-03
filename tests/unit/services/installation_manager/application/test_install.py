from unittest.mock import MagicMock

from services.installation_manager.application.install import InstallUseCase
from services.installation_manager.domain.models import InstallConfig, Job, JobKind
from services.installation_manager.domain.ports import CommandResult
from services.installation_manager.domain.services import AUTH_SECRET_FIELDS


def test_prepare_config_generates_auth_secrets_for_new_installation() -> None:
    settings = MagicMock()
    settings.default_project_name = "dvt"
    settings.lib_dir_host = "/var/lib/dvt"
    library = MagicMock()
    library.read_env.return_value = {}
    use_case = InstallUseCase(
        settings=settings,
        docker=MagicMock(),
        library=library,
        jobs=MagicMock(),
    )
    cfg = InstallConfig()

    use_case._prepare_config(cfg)

    values = [getattr(cfg, field_name) for field_name, _ in AUTH_SECRET_FIELDS]
    assert all(len(value) >= 32 for value in values)
    assert len(set(values)) == len(AUTH_SECRET_FIELDS)


def test_disabled_ai_mcp_is_removed_before_install_compose_up() -> None:
    settings = MagicMock()
    settings.task_worker_service = "task-worker"
    docker = MagicMock()
    docker.compose.side_effect = [
        CommandResult(0, "stopped"),
        CommandResult(0, "removed"),
        CommandResult(0, "started"),
    ]
    library = MagicMock()
    library.compose_path = "/var/lib/dvt/docker-compose.yaml"
    library.env_path = "/var/lib/dvt/.env"
    use_case = InstallUseCase(
        settings=settings,
        docker=docker,
        library=library,
        jobs=MagicMock(),
    )

    use_case._compose_up(
        Job(JobKind.INSTALL, []),
        InstallConfig(ai_mcp_enabled=False),
    )

    commands = [call.kwargs["command"] for call in docker.compose.call_args_list]
    assert commands[:2] == [["stop", "dvt-ai-mcp"], ["rm", "-f", "dvt-ai-mcp"]]
    assert commands[2][0] == "up"
