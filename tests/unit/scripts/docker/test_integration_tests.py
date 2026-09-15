from pathlib import Path

from scripts.docker.integration_tests import PROJECT_DIR, resolve_docker_config_dir


def test_resolve_docker_config_dir_preserves_explicit_value(tmp_path: Path) -> None:
    configured_dir = tmp_path / "ci-docker-config"

    result = resolve_docker_config_dir({"DOCKER_CONFIG": str(configured_dir)})

    assert result == configured_dir


def test_resolve_docker_config_dir_uses_project_fallback() -> None:
    result = resolve_docker_config_dir({})

    assert result == Path(PROJECT_DIR) / "tmp" / "docker-config"


def test_resolve_docker_config_dir_ignores_blank_value() -> None:
    result = resolve_docker_config_dir({"DOCKER_CONFIG": "   "})

    assert result == Path(PROJECT_DIR) / "tmp" / "docker-config"
