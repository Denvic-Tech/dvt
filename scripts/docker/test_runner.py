from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
_TEST_COMPOSE_FILES = (
    "docker/docker-compose.base.yaml",
    "docker/docker-compose.dev.yaml",
    "docker/docker-compose.tests.yaml",
)
_APP_COMPOSE_FILES = (
    "docker/docker-compose.base.yaml",
    "docker/docker-compose.dev.yaml",
)
_PROD_COMPOSE_FILES = (
    "docker/docker-compose.base.yaml",
    "docker/docker-compose.dev.yaml",
    "docker/docker-compose.prod.override.yaml",
)


def run_command(
    command: list[str],
    *,
    env: dict[str, str],
    extra_env: dict[str, str] | None = None,
) -> int:
    command_env = env.copy()
    if extra_env:
        command_env.update(extra_env)
    result = subprocess.run(command, env=command_env)
    return result.returncode


def ensure_external_docker_network(name: str, *, env: dict[str, str]) -> None:
    inspect_result = subprocess.run(
        ["docker", "network", "inspect", name],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if inspect_result.returncode == 0:
        print(f"Docker network '{name}' already exists")
        return
    if inspect_result.returncode != 1:
        raise RuntimeError(
            f"Unable to inspect Docker network '{name}': "
            f"{inspect_result.stderr.strip() or inspect_result.stdout.strip()}"
        )

    print(f"Creating Docker network: {name}")
    create_result = subprocess.run(
        ["docker", "network", "create", name],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if create_result.returncode == 0:
        return

    # A parallel CI job may have created the network after the inspect call.
    retry_inspect_result = subprocess.run(
        ["docker", "network", "inspect", name],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if retry_inspect_result.returncode == 0:
        print(f"Docker network '{name}' was created concurrently")
        return

    raise RuntimeError(
        f"Unable to create Docker network '{name}': "
        f"{create_result.stderr.strip() or create_result.stdout.strip()}"
    )


def parse_test_script_args(argv: list[str] | None = None) -> tuple[str | None, list[str], str | None]:
    parser = argparse.ArgumentParser(
        description="Run dockerized tests with optional targeted test path."
    )
    parser.add_argument(
        "test_path",
        nargs="?",
        default=None,
        help="Optional test file/directory path (or pytest node id with ::) inside the test type root.",
    )
    parser.add_argument(
        "-e",
        "--extension",
        default=None,
        help="Run tests for the named extension only.",
    )
    args, pytest_args = parser.parse_known_args(argv)
    return args.test_path, pytest_args, args.extension


def collect_extension_test_dirs(
    *,
    project_dir: Path,
    tests_type: str,
    extensions_data_dir: str | None = None,
) -> list[str]:
    """Собирает пути к тестам расширений (например 'extensions/Name/tests/unit')."""
    if extensions_data_dir is None:
        extensions_root = Path(
            os.getenv("EXTENSIONS_VOLUME_PATH", project_dir / 'extensions')
        ).resolve()
    else:
        extensions_root = (project_dir / extensions_data_dir).resolve()

    if not extensions_root.is_dir():
        return []

    result: list[str] = []
    for entry in sorted(extensions_root.iterdir()):
        if not entry.is_dir():
            continue
        candidate = entry / "tests" / tests_type
        if not candidate.is_dir():
            continue
        result.append(f"extensions/{entry.name}/tests/{tests_type}")
    return result


def resolve_extension_test_target(
    *,
    project_dir: Path,
    extension_name: str,
    tests_type: str,
    extensions_data_dir: str | None = None,
) -> str:
    """Разрешает путь к тестам конкретного расширения."""
    if extensions_data_dir is None:
        extensions_root = Path(
            os.getenv("EXTENSIONS_VOLUME_PATH", "./extensions")
        ).resolve()
    else:
        extensions_root = (project_dir / extensions_data_dir).resolve()

    for entry in extensions_root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.lower() != extension_name.lower():
            continue
        candidate = entry / "tests" / tests_type
        if not candidate.is_dir():
            raise ValueError(
                f"Extension '{entry.name}' has no tests/{tests_type} directory"
            )
        return f"extensions/{entry.name}/tests/{tests_type}"

    available = [
        e.name for e in sorted(extensions_root.iterdir())
        if e.is_dir() and (e / "tests" / tests_type).is_dir()
    ]
    hint = f" Available: {', '.join(available)}" if available else ""
    raise ValueError(f"Extension '{extension_name}' not found.{hint}")


def resolve_test_target(
    *,
    project_dir: Path,
    tests_dir: str,
    test_path: str | None,
) -> str:
    normalized_tests_dir = tests_dir.replace("\\", "/")
    project_root = project_dir.resolve()
    tests_root = (project_root / normalized_tests_dir).resolve()
    if not tests_root.exists():
        raise ValueError(f"Tests directory not found: {normalized_tests_dir}")

    if test_path is None:
        return normalized_tests_dir

    raw_target = test_path.strip()
    if not raw_target:
        raise ValueError("Test path must not be empty.")

    path_part, separator, node_selector = raw_target.partition("::")
    if not path_part:
        raise ValueError("Test path must include a file or directory before '::'.")

    candidate = Path(path_part)
    if not candidate.is_absolute():
        candidate = project_root / candidate
    resolved_candidate = candidate.resolve()

    if not resolved_candidate.exists():
        raise ValueError(f"Test path not found: {path_part}")

    try:
        resolved_candidate.relative_to(tests_root)
    except ValueError as exc:
        raise ValueError(
            f"Test path must be inside '{normalized_tests_dir}': {path_part}"
        ) from exc

    relative_target = resolved_candidate.relative_to(project_root).as_posix()
    if not separator:
        return relative_target
    if not node_selector:
        raise ValueError("Pytest node selector after '::' must not be empty.")
    return f"{relative_target}::{node_selector}"


def build_testing_compose_command(project_dir: Path, *arguments: str) -> list[str]:
    command = ["docker", "compose", "--project-directory", str(project_dir)]
    for compose_file in _TEST_COMPOSE_FILES:
        command.extend(["-f", compose_file])
    command.extend(["--profile", "testing", *arguments])
    return command


def build_app_compose_command(project_dir: Path, *arguments: str) -> list[str]:
    command = ["docker", "compose", "--project-directory", str(project_dir)]
    for compose_file in _APP_COMPOSE_FILES:
        command.extend(["-f", compose_file])
    command.extend(arguments)
    return command


def build_prod_compose_command(project_dir: Path, *arguments: str) -> list[str]:
    command = ["docker", "compose", "--project-directory", str(project_dir)]
    for compose_file in _PROD_COMPOSE_FILES:
        command.extend(["-f", compose_file])
    command.extend(arguments)
    return command
